"""GitHub — a username's public profile (#4 footprint, #5 identity metadata).

Consumes: username. Free public REST API (api.github.com). An optional token
(ARESCOPE_GITHUB_TOKEN) lifts the rate limit 60→5000/hr; unauthenticated still
works. Surfaces the real-world identity a dev handle leaks: name, location,
company, email, avatar, and the linked Twitter/blog (deanonymization vectors).
"""

from __future__ import annotations

import httpx

from arescope.config import Settings
from arescope.connectors._identity import LINK, from_profile_fields, identity_signal
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_API = "https://api.github.com/users/"


class GitHubConnector(Connector):
    name = "github"
    consumes = {InputType.USERNAME}

    def available(self, cfg: Settings) -> bool:
        return cfg.github_enabled

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        headers = {"accept": "application/vnd.github+json", "user-agent": "arescope-self-audit"}
        if cfg.github_token:
            headers["authorization"] = f"Bearer {cfg.github_token}"
        try:
            resp = httpx.get(f"{_API}{value}", headers=headers, timeout=20, follow_redirects=True)
        except httpx.HTTPError as e:
            raise ConnectorGap(f"github request failed: {e}") from e

        if resp.status_code == 404:
            return []  # no such user — not a gap, just absence
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            raise ConnectorGap("github rate-limited (set ARESCOPE_GITHUB_TOKEN to raise the limit)")
        if resp.status_code >= 400:
            raise ConnectorGap(f"github returned {resp.status_code}")

        data = resp.json() or {}
        profile_url = data.get("html_url")
        signals: list[Signal] = [
            Signal(
                source=self.name,
                kind="account",
                locator="github.com",
                subject_value=value,
                subject_type=InputType.USERNAME,
                raw={
                    "domain": "github.com",
                    "url": profile_url,
                    "public_repos": data.get("public_repos"),
                    "followers": data.get("followers"),
                    "created_at": data.get("created_at"),
                },
            )
        ]

        # Identity attributes the profile leaks. avatar_url is always present on GitHub
        # (it's a default identicon when unset), so only treat it as a real photo when
        # the user uploaded one (gravatar_id non-empty signals a custom avatar).
        fields: dict[str, object] = {
            "name": data.get("name"),
            "location": data.get("location"),
            "company": data.get("company"),
            "bio": data.get("bio"),
        }
        if data.get("gravatar_id") or (data.get("avatar_url") and "?" in str(data.get("avatar_url"))):
            fields["avatar_url"] = data.get("avatar_url")
        signals.extend(
            from_profile_fields(
                source=self.name,
                platform="github.com",
                fields=fields,
                subject_value=value,
                subject_type=InputType.USERNAME,
                profile_url=profile_url,
            )
        )

        # A public email or a linked handle is a direct pivot to other identities.
        if data.get("email"):
            signals.append(
                identity_signal(
                    source=self.name, attribute=LINK, value=str(data["email"]),
                    subject_value=value, subject_type=InputType.USERNAME,
                    platform="github.com", url=f"mailto:{data['email']}",
                )
            )
        if data.get("twitter_username"):
            signals.append(
                identity_signal(
                    source=self.name, attribute=LINK, value=f"@{data['twitter_username']} (x.com)",
                    subject_value=value, subject_type=InputType.USERNAME,
                    platform="github.com", url=f"https://x.com/{data['twitter_username']}",
                )
            )
        if data.get("blog"):
            url = str(data["blog"])
            signals.append(
                identity_signal(
                    source=self.name, attribute=LINK, value=url,
                    subject_value=value, subject_type=InputType.USERNAME,
                    platform="github.com", url=url if url.startswith("http") else f"https://{url}",
                )
            )
        return signals
