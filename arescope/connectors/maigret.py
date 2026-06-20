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
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal


class MaigretConnector(Connector):
    name = "maigret"
    consumes = {InputType.USERNAME}

    def available(self, cfg: Settings) -> bool:
        return cfg.maigret_enabled

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            claimed = _run_maigret(value)
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
        return signals


def _run_maigret(username: str) -> dict[str, dict]:
    """Run `maigret <user> --json simple` and return {site: info} for claimed sites."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [
                "maigret", username,
                "--json", "simple",
                "--no-progressbar",
                "--timeout", "20",
                "--folder", tmp,
            ],
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
        status = info.get("status")
        # "simple" format nests status; be generous about shape across versions.
        is_claimed = (
            (isinstance(status, dict) and status.get("status") == "Claimed")
            or status == "Claimed"
            or info.get("url_user")
        )
        if is_claimed:
            claimed[site] = info
    return claimed
