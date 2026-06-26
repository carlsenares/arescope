"""Regression tests for the map-overhaul fixes (live-run feedback, 2026-06-26).

Covers the pure, network-free seams of each fix:
  * exact first+last name gate on web-search results (`name_matches`)
  * GHunt Maps contributor-review parse (`_parse_maps_reviews` + helpers)
  * Apify Instagram profile-photo emitted even for private accounts
  * unconfirmed data-broker listings collapsed to ONE map node
"""

from __future__ import annotations

from arescope.connectors._webfilter import name_matches


# --- exact name gate ---------------------------------------------------------

def test_name_matches_exact_first_and_last():
    assert name_matches("Patrik Breeck", "Patrik Breeck", None)
    assert name_matches("Patrik Breeck", "de.linkedin.com — Patrik Breeck", "headline")
    # order-independent + accent/case/punctuation folding, but NOT spelling
    assert name_matches("Patrik Breeck", "BREECK, Patrík — bio", None)


def test_name_matches_rejects_lookalikes():
    assert not name_matches("Patrik Breeck", "Patrick Breck | Facebook", "")
    assert not name_matches("Patrik Breeck", "Patrick Breeck", "")  # wrong first-name spelling
    assert not name_matches("Patrik Breeck", "Brad Breeck - IMDb", "biography")
    assert not name_matches("Patrik Breeck", "An Duy Dang holt Gold in Flensburg", "")


def test_name_matches_empty_query_is_permissive():
    assert name_matches("", "anything", None)


def test_name_matches_non_latin_scripts_stay_active():
    # Cyrillic/CJK names must still tokenize (regression: an ASCII-only normalize dropped
    # the letters → empty tokens → filter went permissive and matched everything).
    assert name_matches("Иван Петров", "Профиль: Иван Петров — VK", None)
    assert not name_matches("Иван Петров", "Иван Сидоров", None)
    assert name_matches("山田太郎", "山田太郎のプロフィール", None)
    assert not name_matches("山田太郎", "鈴木一郎 profile", None)


# --- GHunt Maps reviews (count + contributor link) ---------------------------
# The place LIST isn't reliably fetchable (verified live — the locationhistory RPC returns
# only stats, even authenticated), so the connector surfaces the count + a click-through
# contributor URL. We test the two pure extractors that drive that.

def test_gaia_id_and_review_count():
    from arescope.connectors.ghunt import _gaia_id, _maps_review_count
    data = {"PROFILE_CONTAINER": {"profile": {"personId": "113877553740284000332"},
                                  "maps": {"stats": {"Reviews": 4, "Answers": 14}}}}
    assert _gaia_id(data) == "113877553740284000332"
    assert _maps_review_count(data) == 4
    assert _maps_review_count({}) == 0
    assert _gaia_id({}) is None


def test_extract_places_from_rendered_contrib_html():
    from arescope.connectors.ghunt import _extract_places_from_html
    html = (
        '<a href="/maps/place/Caf%C3%A9+Central/data=abc" aria-label="Café Central">x</a>'
        '<a href="/maps/place/G%C3%B6rlitzer+Park/@52.1,13.4,17z">y</a>'
        '<a href="/maps/place/Caf%C3%A9+Central/other">dup</a>'   # de-duped
        '<a href="/maps/place/photo/...">noise</a>'                # dropped
    )
    places = _extract_places_from_html(html)
    assert places == ["Café Central", "Görlitzer Park"]


def test_extract_places_empty_on_private_or_blank():
    from arescope.connectors.ghunt import _extract_places_from_html
    assert _extract_places_from_html("") == []
    assert _extract_places_from_html("<div>Reviews aren't verified</div>") == []


# --- Apify Instagram photo on private accounts -------------------------------

def test_apify_emits_photo_even_when_private(monkeypatch):
    from arescope.connectors import apify as apify_mod
    from arescope.connectors._identity import IDENTITY_KIND
    from arescope.config import Settings

    class _Resp:
        status_code = 200
        def json(self):
            return [{"username": "patrik_brtr", "fullName": "Patrik", "private": True,
                     "followersCount": 62, "profilePicUrlHD": "https://scontent-x.cdninstagram.com/p.jpg"}]

    monkeypatch.setattr(apify_mod.httpx, "post", lambda *a, **k: _Resp())
    cfg = Settings(apify_token="t", apify_instagram_actor="apify/instagram-profile-scraper")
    sigs = apify_mod.ApifyConnector().run("patrik_brtr", apify_mod.InputType.USERNAME, cfg)
    photos = [s for s in sigs if s.kind == IDENTITY_KIND and (s.raw or {}).get("attribute") == "photo"]
    assert len(photos) == 1
    assert "cdninstagram.com" in photos[0].raw["value"]


# --- broker checklist + honest IP note (presenter copy) ----------------------

def test_present_broker_checklist_note():
    from arescope.graph import _present
    note = _present({"type": "broker", "meta": {"confirmed": False, "count": 12, "items": []}})
    assert "12 people-search sites" in note
    assert "none confirmed" in note.lower()


def test_present_iploc_note_is_honest_about_address():
    from arescope.graph import _present
    note = _present({"type": "iploc", "meta": {"location": "Berlin"}})
    assert "not your street address" in note
    assert "city-level" in note


# --- CodeRabbit: don't leak raw exceptions / don't poison the logo cache -------

def test_public_gap_reason_strips_raw_exception():
    from arescope.service import _public_gap_reason
    assert _public_gap_reason("unexpected error: KeyError('container')") == "unexpected error"
    assert _public_gap_reason("ipinfo rejected the token (401)") == "ipinfo rejected the token (401)"
    assert _public_gap_reason(None) == "unavailable"


def test_logo_proxy_caches_on_404_but_not_on_transient(monkeypatch, tmp_path):
    from arescope.web import routes

    class _Resp:
        def __init__(self, status, ctype="image/svg+xml"):
            self.status_code = status
            self.headers = {"content-type": ctype}
            self.content = b"<svg/>"

    monkeypatch.setattr(routes, "_LOGO_CACHE", str(tmp_path))

    # transient (500) → monogram served but NOT written to disk (retry later)
    monkeypatch.setattr(routes.httpx, "get", lambda *a, **k: _Resp(500))
    routes.logo_proxy("spokeo")
    assert not (tmp_path / "spokeo.svg").exists()

    # genuine 404 → monogram cached permanently
    monkeypatch.setattr(routes.httpx, "get", lambda *a, **k: _Resp(404))
    routes.logo_proxy("spokeo")
    assert (tmp_path / "spokeo.svg").exists()
