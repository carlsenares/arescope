"""Gravatar — what a public profile is attached to an email (#5 identity, #4 footprint).

Consumes: email. No key: Gravatar exposes a public JSON profile at
gravatar.com/<md5(email)>.json. This is the cleanest free email→identity signal —
and the seed for the email→discovered-handle unlock (EXTENDED_SEARCH_SCOPE.md): the
profile's `accounts[]` are other platforms the SAME email is verified on, so they're
trickproof-linked handles, not assertions.
"""

from __future__ import annotations

import hashlib

import httpx

from arescope.config import Settings
from arescope.connectors._identity import from_profile_fields
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal


class GravatarConnector(Connector):
    name = "gravatar"
    consumes = {InputType.EMAIL}

    def available(self, cfg: Settings) -> bool:
        return cfg.gravatar_enabled

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        digest = hashlib.md5(value.strip().lower().encode()).hexdigest()  # noqa: S324 (Gravatar spec)
        headers = {"user-agent": "arescope-self-audit", "accept": "application/json"}
        try:
            resp = httpx.get(
                f"https://www.gravatar.com/{digest}.json",
                headers=headers, timeout=20, follow_redirects=True,
            )
        except httpx.HTTPError as e:
            raise ConnectorGap(f"gravatar request failed: {e}") from e

        if resp.status_code in (403, 404):
            return []  # no public Gravatar for this email
        if resp.status_code == 429:
            raise ConnectorGap("gravatar rate-limited (429)")
        if resp.status_code >= 400:
            raise ConnectorGap(f"gravatar returned {resp.status_code}")
        try:
            entries = (resp.json() or {}).get("entry", [])
        except ValueError:
            return []  # gravatar serves an HTML 404 body for some misses
        if not entries:
            return []
        entry = entries[0]
        profile_url = entry.get("profileUrl")

        fields: dict[str, object] = {
            "displayName": entry.get("displayName"),
            "currentLocation": entry.get("currentLocation"),
            "aboutMe": entry.get("aboutMe"),
            "thumbnailUrl": entry.get("thumbnailUrl"),
        }
        if isinstance(entry.get("name"), dict):
            fields["name"] = entry["name"].get("formatted")

        signals: list[Signal] = list(
            from_profile_fields(
                source=self.name,
                platform="gravatar.com",
                fields=fields,
                subject_value=value,
                subject_type=InputType.EMAIL,
                profile_url=profile_url,
            )
        )

        # Linked accounts: same email, other platforms ⇒ discovered (not asserted)
        # handles. Emit as account signals so they converge as site nodes on the map
        # and seed the username-side enrichment.
        for acc in entry.get("accounts", []) or []:
            domain = (acc.get("domain") or acc.get("shortname") or "").lower()
            if not domain:
                continue
            signals.append(
                Signal(
                    source=self.name,
                    kind="account",
                    locator=domain,
                    subject_value=value,
                    subject_type=InputType.EMAIL,
                    raw={
                        "domain": domain,
                        "url": acc.get("url"),
                        "handle": acc.get("username") or acc.get("display"),
                        "verified": acc.get("verified"),
                    },
                )
            )
        return signals
