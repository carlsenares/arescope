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
