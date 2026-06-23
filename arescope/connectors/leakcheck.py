"""LeakCheck — credential / breach exposure with full data fields (#1, #3).

Consumes: email, username, phone. Requires: ARESCOPE_LEAKCHECK_API_KEY (lifetime
Pro plan: 400 email/username + 30 keyword lookups per day). The depth jump over
HIBP: per breach it returns WHICH fields leaked (password / address / phone / DOB),
so a leak that exposed a home address rates higher than a bare membership.

Emits one `breach` Signal per source (same shape HIBP uses, so the clustering /
severity logic applies unchanged). Privacy: we do NOT warehouse leaked plaintext
passwords — only that a password was exposed plus a short masked preview the owner
can recognise (first char + length), so the finding stays actionable without us
becoming a credential store.
"""

from __future__ import annotations

import httpx

from arescope.config import Settings
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_API = "https://leakcheck.io/api/v2/query"

# Safety cap: a heavily-reused/junk address can be in tens of thousands of leaks.
# Clustering collapses them anyway, but we don't want to materialise/persist that
# many Signal rows. The most-relevant breaches arrive first; this is plenty for a
# real person's finding.
_MAX_RESULTS = 60

# LeakCheck field name -> HIBP-canonical data class, so clustering._SALIENT picks up
# the severity-raising classes (password / financial / gov-id / address / phone / dob).
_FIELD_TO_CLASS = {
    "password": "Passwords",
    "address": "Physical addresses",
    "phone": "Phone numbers",
    "dob": "Dates of birth",
    "birthday": "Dates of birth",
    "ssn": "Social security numbers",
    "card": "Credit cards",
    "credit_card": "Credit cards",
}

_TYPE = {
    InputType.EMAIL: "email",
    InputType.USERNAME: "username",
    InputType.PHONE: "phone",
}


class LeakCheckConnector(Connector):
    name = "leakcheck"
    consumes = {InputType.EMAIL, InputType.USERNAME, InputType.PHONE}

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.leakcheck_api_key)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            resp = httpx.get(
                f"{_API}/{value}",
                params={"type": _TYPE.get(input_type, "auto")},
                headers={"X-API-Key": cfg.leakcheck_api_key, "Accept": "application/json"},
                timeout=20,
            )
        except httpx.HTTPError as e:
            raise ConnectorGap(f"leakcheck request failed: {e}") from e

        if resp.status_code == 401:
            raise ConnectorGap("leakcheck rejected the API key (401)")
        if resp.status_code == 422:
            return []  # malformed/unsupported query for this type — nothing to report
        if resp.status_code == 429:
            raise ConnectorGap("leakcheck rate-limited / daily quota exhausted (429)")
        if resp.status_code != 200:
            raise ConnectorGap(f"leakcheck unexpected status {resp.status_code}")

        body = resp.json() or {}
        if not body.get("success", True):
            # success:false is returned for "no results" too — treat as clean.
            return []

        signals: list[Signal] = []
        for entry in (body.get("result") or [])[:_MAX_RESULTS]:
            src = entry.get("source") or {}
            fields = entry.get("fields") or list(entry.keys())
            classes = sorted({
                _FIELD_TO_CLASS[f] for f in fields if f in _FIELD_TO_CLASS
            })
            pw = entry.get("password")
            if pw and "Passwords" not in classes:
                classes.append("Passwords")
            name = src.get("name") or "Unnamed leak"
            signals.append(
                Signal(
                    source=self.name,
                    kind="breach",
                    locator=name,
                    subject_value=value,
                    subject_type=input_type,
                    raw={
                        "title": name,
                        "breach_date": src.get("breach_date"),
                        "data_classes": classes,
                        "is_verified": True,
                        "password_exposed": bool(pw),
                        "password_preview": _mask(pw) if pw else None,
                        "fields": fields,
                    },
                )
            )
        return signals


def _mask(pw: str) -> str:
    """First char + length, e.g. 'h••••••• (8)' — recognisable, not reusable/storable."""
    pw = str(pw)
    return f"{pw[0]}{'•' * max(len(pw) - 1, 0)} ({len(pw)})" if pw else ""
