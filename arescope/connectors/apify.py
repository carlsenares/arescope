"""Apify — admin-only social scraping backbone (#8 content).

Consumes: username. Admin-only + key-gated (ToS-gray scraping; ARESCOPE_APIFY_TOKEN).
Runs an Apify "actor" synchronously and turns the result into an `account` node with
the profile + a sample of recent posts in raw (per-post nodes wait on the content-node
graph change, GRAPH.md §12).

v1 wires the **Instagram** actor (it takes a username). LinkedIn/TikTok actors take a
profile URL, not a bare handle, so they wait until we can feed them a URL (e.g. from
PDL's linkedin_url) — see docs/EXTENDED_SEARCH_PLAN.md. Limits are kept low because
Apify bills per result; absent token/actor => skipped, never a failure.
"""

from __future__ import annotations

import httpx

from arescope.config import Settings
from arescope.connectors._identity import PHOTO, identity_signal
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_RUN = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"


class ApifyConnector(Connector):
    name = "apify"
    consumes = {InputType.USERNAME}
    admin_only = True

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.apify_token and cfg.apify_instagram_actor)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        handle = value.strip().lstrip("@")
        actor = cfg.apify_instagram_actor.replace("/", "~")  # API path form
        try:
            resp = httpx.post(
                _RUN.format(actor=actor),
                params={"token": cfg.apify_token, "timeout": 90, "maxItems": 1},
                json={"usernames": [handle], "resultsLimit": 5},
                timeout=120,
            )
        except httpx.HTTPError as e:
            raise ConnectorGap(f"apify request failed: {e}") from e
        if resp.status_code in (401, 403):
            raise ConnectorGap(f"apify rejected the token ({resp.status_code})")
        if resp.status_code == 402:
            raise ConnectorGap("apify out of credits (402)")
        if resp.status_code not in (200, 201):
            raise ConnectorGap(f"apify returned {resp.status_code}")

        items = resp.json() or []
        if not items:
            return []
        it = items[0] if isinstance(items, list) else items
        if not isinstance(it, dict) or it.get("error"):
            return []
        posts = [
            (p.get("caption") or "")[:280]
            for p in (it.get("latestPosts") or [])[:5]
            if isinstance(p, dict) and p.get("caption")
        ]
        sigs = [Signal(
            source=self.name, kind="account", locator="instagram.com",
            subject_value=value, subject_type=InputType.USERNAME,
            raw={"url": f"https://instagram.com/{handle}", "domain": "instagram.com",
                 "display_name": it.get("fullName"), "description": it.get("biography"),
                 "followers": it.get("followersCount"), "recent_posts": posts},
        )]
        # Profile photo → a face node on the map (the actor returns it; we just never
        # extracted it before). Skip private accounts — the picture isn't public there.
        photo = it.get("profilePicUrlHD") or it.get("profilePicUrl")
        if photo and not it.get("private"):
            sigs.append(identity_signal(
                source=self.name, attribute=PHOTO, value=photo,
                subject_value=value, subject_type=InputType.USERNAME, platform="instagram"))
        return sigs
