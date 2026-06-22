"""Reddit — a username's public presence + activity (#4 footprint, #8 correlation).

Consumes: username. Surfaces account existence, the avatar, and the subreddits the
user is active in — a quiet location/interest leak (r/london, r/cscareerquestions…)
that helps deanonymize a handle.

Access reality (2026): Reddit now 403-blocks the unauthenticated `.json` endpoints
from datacenter IPs (a login wall, not a real 404). So we use the free OAuth
app-only flow when `ARESCOPE_REDDIT_CLIENT_ID/_SECRET` are set (oauth.reddit.com),
and fall back to the public endpoint otherwise. A 403 is reported as a coverage gap —
never as "no account" — so the report can't imply a presence check it couldn't run.
"""

from __future__ import annotations

from collections import Counter

import httpx

from arescope.config import Settings
from arescope.connectors._identity import LOCATION, PHOTO, identity_signal
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_UA = "arescope-self-audit/1.0 (privacy self-audit)"


def _is_oauth(base: str) -> bool:
    return "oauth.reddit.com" in base


class RedditConnector(Connector):
    name = "reddit"
    consumes = {InputType.USERNAME}

    def available(self, cfg: Settings) -> bool:
        return cfg.reddit_enabled

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        base, headers = self._endpoint(cfg)
        about_url = f"{base}/user/{value}/about" + ("" if _is_oauth(base) else ".json")
        try:
            about = httpx.get(about_url, headers=headers, timeout=20, follow_redirects=True)
        except httpx.HTTPError as e:
            raise ConnectorGap(f"reddit request failed: {e}") from e

        if about.status_code == 404:
            return []  # genuinely no such user
        if about.status_code == 403:
            raise ConnectorGap(
                "reddit blocks unauthenticated access from this host — set "
                "ARESCOPE_REDDIT_CLIENT_ID/_SECRET (free app) to enable it"
            )
        if about.status_code == 429:
            raise ConnectorGap("reddit rate-limited (429)")
        if about.status_code >= 400:
            raise ConnectorGap(f"reddit returned {about.status_code}")

        data = (about.json() or {}).get("data", {})
        profile_url = f"https://www.reddit.com/user/{value}"
        signals: list[Signal] = [
            Signal(
                source=self.name,
                kind="account",
                locator="reddit.com",
                subject_value=value,
                subject_type=InputType.USERNAME,
                raw={
                    "domain": "reddit.com",
                    "url": profile_url,
                    "total_karma": data.get("total_karma"),
                    "created_utc": data.get("created_utc"),
                    "verified": data.get("verified"),
                },
            )
        ]

        # A custom avatar (not the default snoo) is a real photo of/for the user.
        icon = (data.get("snoovatar_img") or data.get("icon_img") or "").split("?")[0]
        if icon and "avatar_default" not in icon and "snoo" not in icon.rsplit("/", 1)[-1]:
            signals.append(
                identity_signal(
                    source=self.name, attribute=PHOTO, value=icon,
                    subject_value=value, subject_type=InputType.USERNAME,
                    platform="reddit.com", url=icon,
                )
            )

        # Active subreddits = an interest/location fingerprint. Best-effort: a dead
        # comments endpoint must not sink the account signal.
        subs = self._top_subreddits(value, base, headers)
        if subs:
            signals.append(
                identity_signal(
                    source=self.name, attribute=LOCATION,
                    value="active in r/" + ", r/".join(subs),
                    subject_value=value, subject_type=InputType.USERNAME,
                    platform="reddit.com", url=profile_url,
                )
            )
        return signals

    def _endpoint(self, cfg: Settings) -> tuple[str, dict]:
        """(base_url, headers). Uses the free OAuth app-only token when configured."""
        headers = {"user-agent": _UA, "accept": "application/json"}
        cid = getattr(cfg, "reddit_client_id", "")
        secret = getattr(cfg, "reddit_client_secret", "")
        if cid and secret:
            try:
                tok = httpx.post(
                    "https://www.reddit.com/api/v1/access_token",
                    data={"grant_type": "client_credentials"},
                    auth=(cid, secret), headers={"user-agent": _UA}, timeout=20,
                )
                if tok.status_code == 200:
                    headers["authorization"] = f"Bearer {tok.json()['access_token']}"
                    return "https://oauth.reddit.com", headers
            except (httpx.HTTPError, KeyError, ValueError):
                pass  # fall back to the public endpoint (will likely 403 → honest gap)
        return "https://www.reddit.com", headers

    def _top_subreddits(self, username: str, base: str, headers: dict, *, limit: int = 5) -> list[str]:
        suffix = "/comments?limit=100" if _is_oauth(base) else "/comments.json?limit=100"
        try:
            resp = httpx.get(
                f"{base}/user/{username}{suffix}",
                headers=headers, timeout=20, follow_redirects=True,
            )
            if resp.status_code >= 400:
                return []
            children = (resp.json() or {}).get("data", {}).get("children", [])
        except (httpx.HTTPError, ValueError):
            return []
        counts = Counter(
            c.get("data", {}).get("subreddit")
            for c in children
            if c.get("data", {}).get("subreddit")
        )
        return [name for name, _ in counts.most_common(limit)]
