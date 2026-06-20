"""Hudson Rock (Cavalier) — infostealer-log exposure (#2).

Consumes: email, username. Free tier, no key. Highest-signal "critical": means
the user's device was infected and creds + session cookies were exfiltrated.
"""

from __future__ import annotations

import httpx

from arescope.config import Settings
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_API = "https://cavalier.hudsonrock.com/api/json/v2/osint-tools"


class HudsonRockConnector(Connector):
    name = "hudsonrock"
    consumes = {InputType.EMAIL, InputType.USERNAME}

    def available(self, cfg: Settings) -> bool:
        return cfg.hudsonrock_enabled

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        if input_type is InputType.EMAIL:
            endpoint, param = "search-by-email", "email"
        else:
            endpoint, param = "search-by-username", "username"

        try:
            resp = httpx.get(
                f"{_API}/{endpoint}", params={param: value}, timeout=20
            )
        except httpx.HTTPError as e:
            raise ConnectorGap(f"hudsonrock request failed: {e}") from e

        if resp.status_code == 429:
            raise ConnectorGap("hudsonrock rate-limited (429)")
        if resp.status_code != 200:
            raise ConnectorGap(f"hudsonrock unexpected status {resp.status_code}")

        data = resp.json()
        stealers = data.get("stealers") or []
        if not stealers:
            return []  # not found in any infostealer log

        signals: list[Signal] = []
        for stealer in stealers:
            signals.append(
                Signal(
                    source=self.name,
                    kind="stealer_log",
                    locator=(
                        stealer.get("stealer_family")
                        or stealer.get("computer_name")
                        or stealer.get("date_compromised")
                        or "stealer log"
                    ),
                    subject_value=value,
                    subject_type=input_type,
                    raw={
                        "date_compromised": stealer.get("date_compromised"),
                        "computer_name": stealer.get("computer_name"),
                        "operating_system": stealer.get("operating_system"),
                        "malware_path": stealer.get("malware_path"),
                        "antiviruses": stealer.get("antiviruses"),
                        "top_passwords": stealer.get("top_passwords"),
                        "top_logins": stealer.get("top_logins"),
                    },
                )
            )
        return signals
