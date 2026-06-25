"""Instagram public content via Camoufox (admin-only, free alternative to the Apify actor).

Consumes: username. Instagram blocks plain HTTP clients, so we fetch its
`web_profile_info` JSON endpoint through the stealth browser context (browser.py). With
a stored session (`ARESCOPE_INSTAGRAM_SESSION_PATH`, a Playwright storage-state JSON the
founder exports once) it gets the logged-in view; without one it gets whatever the
public profile exposes. Emits the SAME `account` signal shape as the Apify/Bluesky
connectors — display name, bio, follower count, profile photo, and a sample of recent
post captions/locations — so it rides the existing clustering + the new post-node graph
rendering with no special-casing.

admin_only: ToS-gray scraping crosses the self-audit line on the user tier until the
per-user-session model exists. UNVALIDATED end-to-end (no live IG session tested); a
block/empty response degrades to a coverage gap.
"""

from __future__ import annotations

from arescope.config import Settings
from arescope.connectors import browser
from arescope.connectors.base import Connector, ConnectorGap
from arescope.connectors._identity import LOCATION, PHOTO, identity_signal
from arescope.schemas import InputType, Signal

# Instagram's public web app id — required header for the web_profile_info endpoint.
_IG_APP_ID = "936619743392459"
_PROFILE_API = "https://www.instagram.com/api/v1/users/web_profile_info/?username={handle}"
_MAX_POSTS = 8


def _parse_web_profile_info(data: dict, handle: str) -> list[Signal]:
    """Pure parse of the web_profile_info JSON into Signals (testable without a browser)."""
    user = ((data or {}).get("data") or {}).get("user") or {}
    if not user:
        return []

    posts: list[str] = []
    locations: list[str] = []
    media = (user.get("edge_owner_to_timeline_media") or {}).get("edges") or []
    for edge in media[:_MAX_POSTS]:
        node = edge.get("node") or {}
        caps = (node.get("edge_media_to_caption") or {}).get("edges") or []
        if caps:
            text = ((caps[0] or {}).get("node") or {}).get("text")
            if text:
                posts.append(text[:280])
        loc = node.get("location") or {}
        if loc.get("name"):
            locations.append(loc["name"])

    handle = handle.lstrip("@")
    photo = user.get("profile_pic_url_hd") or user.get("profile_pic_url")
    signals: list[Signal] = [Signal(
        source="instagram_web", kind="account", locator="instagram.com",
        subject_value=handle, subject_type=InputType.USERNAME,
        raw={
            "url": f"https://instagram.com/{handle}", "domain": "instagram.com",
            "display_name": user.get("full_name"),
            "description": user.get("biography"),
            "followers": (user.get("edge_followed_by") or {}).get("count"),
            "is_private": user.get("is_private"),
            "is_verified": user.get("is_verified"),
            "recent_posts": posts,
        },
    )]
    if photo and not user.get("is_private"):
        signals.append(identity_signal(
            source="instagram_web", attribute=PHOTO, value=photo,
            subject_value=handle, subject_type=InputType.USERNAME, platform="instagram"))
    # A tagged post location is a real-world inference (where they were) — one node each.
    for place in dict.fromkeys(locations):  # dedupe, keep order
        signals.append(identity_signal(
            source="instagram_web", attribute=LOCATION, value=place,
            subject_value=handle, subject_type=InputType.USERNAME, platform="instagram"))
    return signals


class InstagramWebConnector(Connector):
    name = "instagram_web"
    consumes = {InputType.USERNAME}
    admin_only = True

    def available(self, cfg: Settings) -> bool:
        return cfg.browser_scraping_enabled and browser.available()

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        handle = value.strip().lstrip("@")
        if not handle:
            return []
        result = browser.fetch(
            _PROFILE_API.format(handle=handle),
            headers={"x-ig-app-id": _IG_APP_ID, "Accept": "application/json"},
            storage_state_path=cfg.instagram_session_path or None,
        )
        if result.status == 404:
            return []  # no such public profile — clean, not a gap
        if result.status != 200:
            raise ConnectorGap(f"instagram returned {result.status} (login wall / block)")
        return _parse_web_profile_info(result.json(), handle)
