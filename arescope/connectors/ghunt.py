"""GHunt — what a Google account reveals about an email (#5 identity metadata).

Consumes: email. The most universal identity lever we have — most adults have a
Google account — returning the profile photo, Google Maps review history (the places
they frequent: a strong location signal), and linked Google services.

Operational reality (EXTENDED_SEARCH_SCOPE.md, verified 2026): GHunt needs a Google
session the operator supplies once via `ghunt login`; it is fragile (Google breaks it
periodically) and its display-name retrieval has been unreliable since ~2024 — but
the photo + Maps signals still land. So it's config-gated on ARESCOPE_GHUNT_CREDS_PATH
and every failure/drift degrades to a coverage gap, never a scan failure.

NOTE: unvalidated end-to-end here (no Google cookie in this environment). The JSON
shape is parsed defensively; treat field extraction as best-effort until run live.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

from arescope.config import Settings
from arescope.connectors import browser
from arescope.connectors._identity import LOCATION, NAME, PHOTO, identity_signal
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

log = logging.getLogger("arescope.ghunt")

# GHunt only reads creds from this fixed location (no flag, no env override — verified
# against ghunt 2.3.4). We stage the operator's creds file here before running.
_GHUNT_DEFAULT_CREDS = Path.home() / ".malfrats" / "ghunt" / "creds.m"

# --- Google Maps contributor reviews -----------------------------------------
# GHunt's `email` JSON gives the Maps review COUNT but never the place names, and the
# `locationhistory/preview/mas` RPC returns only stats even with GHunt's auth (verified
# live 2026-06-26 — that's why GHunt's own review loop is commented out). The places DO
# render on the public contributor page, but only when the account's contributions are
# PUBLIC; Google defaults them to private (the target tested here is private => the page
# renders no review feed). So we attempt a best-effort browser render to pull the places,
# and degrade to "COUNT + contributor link" when they aren't public — the honest outcome
# either way (a private profile is itself a useful self-audit finding: not leaking).
_MAPS_CONTRIB_URL = "https://www.google.com/maps/contrib/{gaia}/reviews?hl=en"
_MAPS_MAX_PLACES = 15
# Junk slugs that aren't real places (UI chrome that also lives under /maps/place/-ish).
_MAPS_PLACE_NOISE = {"", "photo", "photos", "directions"}


class GHuntConnector(Connector):
    name = "ghunt"
    consumes = {InputType.EMAIL}

    def available(self, cfg: Settings) -> bool:
        # Gate on the operator having opted in (run `ghunt login` and pointed us at
        # the creds). We can't probe the CLI/cookie validity without running it.
        return bool(cfg.ghunt_creds_path)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            data = _run_ghunt(value, cfg.ghunt_creds_path)
        except FileNotFoundError as e:
            raise ConnectorGap("ghunt CLI not found on PATH") from e
        except subprocess.TimeoutExpired as e:
            raise ConnectorGap("ghunt timed out") from e
        except Exception as e:  # auth expired, Google block, JSON drift — all => gap
            raise ConnectorGap(f"ghunt run failed: {e}") from e

        if not data:
            return []  # no public Google account for this email

        gaia_id = _gaia_id(data)
        signals: list[Signal] = [
            Signal(
                source=self.name,
                kind="account",
                locator="google.com",
                subject_value=value,
                subject_type=InputType.EMAIL,
                raw={"domain": "google.com", "gaia_id": gaia_id},
            )
        ]

        photo, is_default = _profile_photo(data)
        if photo:
            signals.append(identity_signal(
                source=self.name, attribute=PHOTO, value=photo,
                subject_value=value, subject_type=InputType.EMAIL,
                platform="google.com", url=photo,
                # is_default=True => Google's generated monogram (no real image public);
                # False => a real uploaded photo (likely the person's face).
                meta={"is_default": is_default},
            ))
        name = _first_str(data, ("name", "profileName", "fullName"))
        if name:
            signals.append(identity_signal(
                source=self.name, attribute=NAME, value=name,
                subject_value=value, subject_type=InputType.EMAIL, platform="google.com",
            ))

        # Google Maps reviews → a real-world location footprint (the places the person
        # reviewed). Best-effort: render the public contributor page and pull the place
        # names; if the account's contributions are private (Google's default) the feed is
        # empty, so degrade to "COUNT + contributor link" (the owner can click through).
        review_count = _maps_review_count(data)
        if gaia_id and review_count:
            places = _maps_review_places(gaia_id, cfg)
            if places:
                for place in places[:_MAPS_MAX_PLACES]:
                    signals.append(identity_signal(
                        source=self.name, attribute=LOCATION, value=place,
                        subject_value=value, subject_type=InputType.EMAIL,
                        platform="maps.google.com"))
            else:
                signals.append(identity_signal(
                    source=self.name, attribute=LOCATION,
                    value=f"{review_count} Google Maps review{'s' if review_count != 1 else ''}",
                    url=_MAPS_CONTRIB_URL.format(gaia=gaia_id),
                    subject_value=value, subject_type=InputType.EMAIL,
                    platform="maps.google.com"))
        return signals


# --- driving + defensive parsing --------------------------------------------

def _run_ghunt(email: str, creds_path: str) -> dict:
    # GHunt reads creds only from _GHUNT_DEFAULT_CREDS. If the operator pointed us at a
    # creds file elsewhere (e.g. copied onto the server), stage it into place first.
    if creds_path and Path(creds_path).is_file() \
            and Path(creds_path).resolve() != _GHUNT_DEFAULT_CREDS.resolve():
        _GHUNT_DEFAULT_CREDS.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(creds_path, _GHUNT_DEFAULT_CREDS)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "ghunt.json"
        subprocess.run(
            ["ghunt", "email", email, "--json", str(out)],
            capture_output=True, timeout=120, check=False,
        )
        if not out.exists():
            return {}
        text = out.read_text() or ""
        return json.loads(text) if text.strip() else {}


def _walk(obj: Any):
    """Yield every (key, value) and value while walking a nested dict/list."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(obj, list):
        for item in obj:
            yield None, item
            yield from _walk(item)


def _profile_photo(data: dict) -> tuple[str | None, bool]:
    """The profile photo URL + whether it's Google's default monogram avatar.

    GHunt's people JSON gives each photo as `{ "url": ..., "isDefault": bool }`
    (profilePhotos.PROFILE). We read that structured pair so we can tell a real
    uploaded picture from the letter-monogram default. Falls back to the first
    photo-shaped URL (default unknown => treated as real) if the shape drifts.
    """
    for _k, v in _walk(data):
        if isinstance(v, dict) and "isDefault" in v:
            url = v.get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url, bool(v.get("isDefault"))
    return _find_first(data, _looks_like_photo), False


def _looks_like_photo(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("http")
        and ("googleusercontent" in value or "/photo" in value or value.endswith((".jpg", ".png")))
    )


def _find_first(data: dict, predicate) -> str | None:
    for _k, v in _walk(data):
        if predicate(v):
            return v
    return None


def _first_str(data: dict, keys: tuple[str, ...]) -> str | None:
    wanted = {k.lower() for k in keys}
    for k, v in _walk(data):
        if isinstance(k, str) and k.lower() in wanted and isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _gaia_id(data: dict) -> str | None:
    """The numeric Google account id (gaia), used to address the Maps contributor RPC.

    GHunt's email JSON exposes it as profile.personId; fall back to any gaia-ish key."""
    pid = _first_str(data, ("personId", "gaia", "gaia_id"))
    if pid and pid.isdigit():
        return pid
    # last resort: a long all-digit value anywhere (gaia ids are ~21 digits)
    for _k, v in _walk(data):
        if isinstance(v, str) and v.isdigit() and len(v) >= 18:
            return v
    return None


def _maps_review_count(data: dict) -> int:
    """The Reviews count from PROFILE_CONTAINER/maps/stats (0 if absent)."""
    for k, v in _walk(data):
        if isinstance(k, str) and k.lower() == "reviews" and isinstance(v, int):
            return v
    return 0


def _maps_review_places(gaia_id: str, cfg: Settings) -> list[str]:
    """Render the public contributor reviews page and extract the reviewed place names.

    Requires the stealth browser (the feed is JS-rendered); without it, or if the
    contributions aren't public, returns [] and the caller degrades to count + link.
    Never raises — a browser/Google failure is just "no places".
    """
    if not (cfg.browser_scraping_enabled and browser.available()):
        return []
    try:
        result = browser.render(
            _MAPS_CONTRIB_URL.format(gaia=gaia_id),
            wait_selector='a[href*="/maps/place/"]', wait_ms=6000, scroll_rounds=4)
    except ConnectorGap as e:
        log.info("ghunt maps render failed: %s", e)
        return []
    return _extract_places_from_html(result.html)


def _extract_places_from_html(html: str) -> list[str]:
    """Pure parse: pull reviewed place names out of a rendered contributor page.

    Each review card links to its place via `/maps/place/<Slug>/…`; the URL slug decodes
    to the readable place name (order-independent, robust to Google's churning CSS
    classes). De-duped, noise slugs dropped. Empty input / no reviews => []."""
    places: list[str] = []
    for slug in re.findall(r'/maps/place/([^"/?\\\s]+)', html or ""):
        name = urllib.parse.unquote(slug).replace("+", " ").strip()
        if name and name.lower() not in _MAPS_PLACE_NOISE and not name.startswith("@"):
            places.append(name)
    seen: set[str] = set()
    return [p for p in places if not (p.lower() in seen or seen.add(p.lower()))]
