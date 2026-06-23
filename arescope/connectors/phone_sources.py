"""Phone-number enrichment (input type: phone).

- IPQS      — fraud/spam reputation + line type (VOIP vs mobile matters for SIM-swap).
- NumVerify — validation: carrier / country / line type (also map enrichment).

Both key-gated and graceful. They emit `phone_risk` / `phone_meta` Signals
(clustering maps both to ACCOUNT_METADATA — "what your number reveals / how exposed
it is"). Phone breach exposure itself comes from LeakCheck (type=phone), shaped as a
`breach`, so it rates through the credential/breach path like an email leak.
"""

from __future__ import annotations

import httpx

from arescope.config import Settings
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal


class IPQSPhoneConnector(Connector):
    name = "ipqs"
    consumes = {InputType.PHONE}

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.ipqs_api_key)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            resp = httpx.get(
                f"https://www.ipqualityscore.com/api/json/phone/{cfg.ipqs_api_key}/{value}",
                timeout=15,
            )
        except httpx.HTTPError as e:
            raise ConnectorGap(f"ipqs request failed: {e}") from e
        if resp.status_code == 429:
            raise ConnectorGap("ipqs rate-limited (429)")
        if resp.status_code != 200:
            raise ConnectorGap(f"ipqs unexpected status {resp.status_code}")
        d = resp.json() or {}
        if not d.get("success", True):
            raise ConnectorGap(f"ipqs error: {d.get('message')}")
        return [Signal(
            source=self.name, kind="phone_risk", locator=value,
            subject_value=value, subject_type=InputType.PHONE,
            raw={
                "valid": d.get("valid"), "fraud_score": d.get("fraud_score"),
                "recent_abuse": d.get("recent_abuse"), "risky": d.get("risky"),
                "spammer": d.get("spammer"), "line_type": d.get("line_type"),
                "carrier": d.get("carrier"), "country": d.get("country"),
                "active": d.get("active"), "leaked": d.get("leaked"),
            },
        )]


class NumVerifyConnector(Connector):
    name = "numverify"
    consumes = {InputType.PHONE}

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.numverify_api_key)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        # NumVerify free tier is HTTP-only (https is a paid feature).
        try:
            resp = httpx.get(
                "http://apilayer.net/api/validate",
                params={"access_key": cfg.numverify_api_key, "number": value},
                timeout=15,
            )
        except httpx.HTTPError as e:
            raise ConnectorGap(f"numverify request failed: {e}") from e
        if resp.status_code != 200:
            raise ConnectorGap(f"numverify unexpected status {resp.status_code}")
        d = resp.json() or {}
        if d.get("success") is False or "valid" not in d:
            raise ConnectorGap(f"numverify error: {(d.get('error') or {}).get('info', 'unknown')}")
        if not d.get("valid"):
            return []  # not a valid number — nothing to report
        return [Signal(
            source=self.name, kind="phone_meta", locator=value,
            subject_value=value, subject_type=InputType.PHONE,
            raw={
                "carrier": d.get("carrier"), "line_type": d.get("line_type"),
                "country_code": d.get("country_code"), "country": d.get("country_name"),
                "location": d.get("location"),
                "international_format": d.get("international_format"),
            },
        )]
