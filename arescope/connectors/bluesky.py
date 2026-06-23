"""Bluesky (AT Protocol) — public profile + recent posts for a username (#4,#8).

Consumes: username. Free, open, no key. Resolves `<handle>` (bare username →
`<username>.bsky.social`) and emits one `account` node carrying the profile + a
sample of recent post text, plus the display name as an identity attribute. Per-post
*nodes* wait on the content-node graph change (GRAPH.md §12); for now the posts ride
in the account node's raw so the data is captured + available to Evaluate.
"""

from __future__ import annotations

import httpx

from arescope.config import Settings
from arescope.connectors._identity import identity_signal
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_API = "https://public.api.bsky.app/xrpc"


class BlueskyConnector(Connector):
    name = "bluesky"
    consumes = {InputType.USERNAME}

    def available(self, cfg: Settings) -> bool:
        return cfg.bluesky_enabled

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        handle = value.strip().lstrip("@")
        if "." not in handle:
            handle = f"{handle}.bsky.social"
        try:
            prof = httpx.get(f"{_API}/app.bsky.actor.getProfile",
                             params={"actor": handle}, timeout=15)
        except httpx.HTTPError as e:
            raise ConnectorGap(f"bluesky request failed: {e}") from e
        if prof.status_code in (400, 404):
            return []  # no such handle — clean
        if prof.status_code == 429:
            raise ConnectorGap("bluesky rate-limited (429)")
        if prof.status_code != 200:
            raise ConnectorGap(f"bluesky returned {prof.status_code}")

        p = prof.json() or {}
        posts: list[str] = []
        try:
            feed = httpx.get(f"{_API}/app.bsky.feed.getAuthorFeed",
                             params={"actor": handle, "limit": 10}, timeout=15)
            if feed.status_code == 200:
                for item in (feed.json() or {}).get("feed", []):
                    text = ((item.get("post") or {}).get("record") or {}).get("text")
                    if text:
                        posts.append(text[:280])
        except httpx.HTTPError:
            pass  # posts are a bonus; the profile alone is still worth a node

        signals: list[Signal] = [Signal(
            source=self.name, kind="account", locator="bsky.app",
            subject_value=value, subject_type=InputType.USERNAME,
            raw={"url": f"https://bsky.app/profile/{handle}", "domain": "bsky.app",
                 "display_name": p.get("displayName"), "description": p.get("description"),
                 "followers": p.get("followersCount"), "posts_count": p.get("postsCount"),
                 "recent_posts": posts},
        )]
        if p.get("displayName"):
            signals.append(identity_signal(
                source=self.name, attribute="name", value=p["displayName"],
                subject_value=value, subject_type=InputType.USERNAME, platform="bluesky"))
        return signals
