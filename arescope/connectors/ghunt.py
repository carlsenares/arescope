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
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

# GHunt only reads creds from this fixed location (no flag, no env override — verified
# against ghunt 2.3.4). We stage the operator's creds file here before running.
_GHUNT_DEFAULT_CREDS = Path.home() / ".malfrats" / "ghunt" / "creds.m"

from arescope.config import Settings
from arescope.connectors._identity import LOCATION, NAME, PHOTO, identity_signal
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal


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

        signals: list[Signal] = [
            Signal(
                source=self.name,
                kind="account",
                locator="google.com",
                subject_value=value,
                subject_type=InputType.EMAIL,
                raw={"domain": "google.com", "gaia_id": _first_str(data, ("gaia", "gaia_id", "id"))},
            )
        ]

        photo = _find_first(data, _looks_like_photo)
        if photo:
            signals.append(identity_signal(
                source=self.name, attribute=PHOTO, value=photo,
                subject_value=value, subject_type=InputType.EMAIL,
                platform="google.com", url=photo,
            ))
        name = _first_str(data, ("name", "profileName", "fullName"))
        if name:
            signals.append(identity_signal(
                source=self.name, attribute=NAME, value=name,
                subject_value=value, subject_type=InputType.EMAIL, platform="google.com",
            ))
        # Google Maps reviews → places the person has been (location footprint).
        for place in _maps_places(data)[:15]:
            signals.append(identity_signal(
                source=self.name, attribute=LOCATION, value=place,
                subject_value=value, subject_type=InputType.EMAIL,
                platform="maps.google.com",
            ))
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


def _maps_places(data: dict) -> list[str]:
    """Best-effort: pull location/place strings out of a Maps-reviews structure."""
    places: list[str] = []
    for k, v in _walk(data):
        if isinstance(k, str) and k.lower() in ("address", "location", "place", "name") \
                and isinstance(v, str) and v.strip():
            places.append(v.strip())
    # de-dup, preserve order
    seen: set[str] = set()
    return [p for p in places if not (p.lower() in seen or seen.add(p.lower()))]
