"""Maigret — account enumeration + username correlation across 100s of sites (#4, #8).

Consumes: username. Free, self-hosted. We drive the Maigret CLI with JSON output
(more stable across releases than its internal Python API) and parse claimed
accounts. Any failure => ConnectorGap.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from arescope.config import Settings
from arescope.connectors._identity import from_profile_fields
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

# Sites whose Maigret absence-detection is broken and report EVERY username as
# "Claimed" (soft-404: they serve HTTP 200 + a profile-shaped page for handles that
# don't exist, and their `absenceStrs` marker has gone stale upstream). Left in, they
# produce a false "you have an account here" finding on every single scan. Match is
# case-insensitive on the Maigret site name. Verified live for Odysee (2026-06-23).
_FALSE_POSITIVE_SITES = frozenset({
    "odysee",
})


class MaigretConnector(Connector):
    name = "maigret"
    consumes = {InputType.USERNAME}

    def available(self, cfg: Settings) -> bool:
        return cfg.maigret_enabled

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            claimed = _run_maigret(value, top_sites=cfg.maigret_top_sites)
        except FileNotFoundError as e:
            raise ConnectorGap("maigret CLI not found on PATH") from e
        except subprocess.TimeoutExpired as e:
            raise ConnectorGap("maigret timed out") from e
        except Exception as e:
            raise ConnectorGap(f"maigret run failed: {e}") from e

        signals: list[Signal] = []
        for site, info in claimed.items():
            signals.append(
                Signal(
                    source=self.name,
                    kind="account",
                    locator=site,
                    subject_value=value,
                    subject_type=InputType.USERNAME,
                    raw={
                        "url": info.get("url_user"),
                        "tags": info.get("tags"),
                        "ids": info.get("ids"),
                    },
                )
            )
            # Metadata mining (EXTENDED_SEARCH_SCOPE.md): Maigret already extracts
            # per-profile fields into `ids` (name, location, image, bio…) — we used
            # only existence before. Turn the recognised ones into identity signals,
            # for free, from the user's own public profiles.
            ids = info.get("ids")
            if isinstance(ids, dict):
                signals.extend(
                    from_profile_fields(
                        source=self.name,
                        platform=site.lower(),
                        fields=ids,
                        subject_value=value,
                        subject_type=InputType.USERNAME,
                        profile_url=info.get("url_user"),
                    )
                )
        return signals


def _run_maigret(username: str, top_sites: int | None = None) -> dict[str, dict]:
    """Run `maigret <user> --json simple` and return {site: info} for claimed sites.

    top_sites caps the search to the N most popular sites (much faster); None uses
    Maigret's default set.
    """
    cmd = [
        "maigret", username,
        "--json", "simple",
        "--no-progressbar",
        "--timeout", "20",
        "--folder", "{tmp}",
    ]
    if top_sites:
        cmd += ["--top-sites", str(top_sites)]
    with tempfile.TemporaryDirectory() as tmp:
        cmd[cmd.index("{tmp}")] = tmp
        subprocess.run(
            cmd,
            capture_output=True,
            timeout=300,
            check=False,
        )
        reports = list(Path(tmp).glob("*.json"))
        if not reports:
            return {}
        data = json.loads(reports[0].read_text())

    claimed: dict[str, dict] = {}
    for site, info in data.items():
        if not isinstance(info, dict):
            continue
        if site.strip().lower() in _FALSE_POSITIVE_SITES:
            continue  # known soft-404 site — its "Claimed" is meaningless
        status = info.get("status")
        # Require an EXPLICIT "Claimed" status. The "simple" format nests it under
        # status.status; tolerate a bare string for older releases. We deliberately do
        # NOT treat the mere presence of url_user as claimed — Maigret builds that
        # candidate URL for every site it checks, claimed or not, so trusting it turned
        # every probed site into a false positive.
        is_claimed = (
            (isinstance(status, dict) and status.get("status") == "Claimed")
            or status == "Claimed"
        )
        if is_claimed:
            claimed[site] = info
    return claimed
