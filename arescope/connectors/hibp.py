"""Have I Been Pwned — breach membership + data classes (#1, #3).

Consumes: email. Requires: ARESCOPE_HIBP_API_KEY (paid, ~cheap monthly).
Absent key => not available => coverage gap (never a failure).
"""

from __future__ import annotations

import httpx

from arescope.config import Settings
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_API = "https://haveibeenpwned.com/api/v3"


class HIBPConnector(Connector):
    name = "hibp"
    consumes = {InputType.EMAIL}

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.hibp_api_key)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        headers = {
            "hibp-api-key": cfg.hibp_api_key,
            "user-agent": "arescope-self-audit",
        }
        url = f"{_API}/breachedaccount/{value}"
        try:
            resp = httpx.get(
                url, headers=headers, params={"truncateResponse": "false"}, timeout=20
            )
        except httpx.HTTPError as e:  # network/transport
            raise ConnectorGap(f"hibp request failed: {e}") from e

        if resp.status_code == 404:
            return []  # clean — no breaches
        if resp.status_code == 401:
            raise ConnectorGap("hibp rejected the API key (401)")
        if resp.status_code == 429:
            raise ConnectorGap("hibp rate-limited (429)")
        if resp.status_code != 200:
            raise ConnectorGap(f"hibp unexpected status {resp.status_code}")

        signals: list[Signal] = []
        for breach in resp.json():
            signals.append(
                Signal(
                    source=self.name,
                    kind="breach",
                    locator=breach.get("Name", "unknown"),
                    subject_value=value,
                    subject_type=InputType.EMAIL,
                    raw={
                        "title": breach.get("Title"),
                        "breach_date": breach.get("BreachDate"),
                        "data_classes": breach.get("DataClasses", []),
                        "is_verified": breach.get("IsVerified"),
                        "description": breach.get("Description"),
                    },
                )
            )
        return signals
