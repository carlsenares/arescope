"""Telegram public username profile photo lookup.

Consumes: username. Telegram does not expose phone-number -> profile photo lookup, but
public usernames have a public preview page at t.me/<username>. When that preview
publishes an og:image/profile image, emit the standard photo identity_attribute so the
existing clustering and identity-map photo node rendering can use it.

This is intentionally narrow: no phone lookup, no login/session, and no hard failure
when Telegram blocks or omits metadata.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from arescope.config import Settings
from arescope.connectors import browser
from arescope.connectors._identity import PHOTO, identity_signal
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")
_DEFAULT_IMAGE_MARKERS = (
    "/img/t_logo",
    "/img/telegram_",
    "/img/website_icon",
    "telegram.org/img/",
)


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
            return
        if tag != "meta":
            return
        attr_map = {k.lower(): v for k, v in attrs if v}
        key = (attr_map.get("property") or attr_map.get("name") or "").strip().lower()
        content = (attr_map.get("content") or "").strip()
        if key and content:
            self.meta[key] = content

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def _clean_username(value: str) -> str:
    value = value.strip().removeprefix("@")
    if value.startswith("https://t.me/") or value.startswith("http://t.me/"):
        value = urlparse(value).path.strip("/").split("/", 1)[0]
    return value


def _public_photo_url(meta: dict[str, str]) -> str | None:
    for key in ("og:image", "twitter:image", "profile:image"):
        url = (meta.get(key) or "").strip()
        if not url.startswith(("https://", "http://")):
            continue
        lowered = url.lower()
        if any(marker in lowered for marker in _DEFAULT_IMAGE_MARKERS):
            continue
        return url
    return None


def _parse_tme_profile(html: str, username: str) -> list[Signal]:
    parser = _MetaParser()
    parser.feed(html or "")
    meta = parser.meta
    title = meta.get("og:title") or parser.title.strip()
    description = meta.get("og:description")
    profile_url = f"https://t.me/{username}"

    # t.me can return branded fallback pages; require profile-specific metadata before
    # claiming an account exists.
    has_profile_metadata = (
        bool(title and ("telegram" not in title.lower() or username.lower() in title.lower()))
        or bool(description and username.lower() in description.lower())
        or bool(_public_photo_url(meta))
    )
    if not has_profile_metadata:
        return []

    signals: list[Signal] = [
        Signal(
            source="telegram",
            kind="account",
            locator="t.me",
            subject_value=username,
            subject_type=InputType.USERNAME,
            raw={
                "url": profile_url,
                "domain": "t.me",
                "display_name": title,
                "description": description,
            },
        )
    ]

    photo = _public_photo_url(meta)
    if photo:
        signals.append(identity_signal(
            source="telegram",
            attribute=PHOTO,
            value=photo,
            subject_value=username,
            subject_type=InputType.USERNAME,
            platform="telegram",
            url=photo,
            meta={"profile_url": profile_url},
        ))
    return signals


class TelegramConnector(Connector):
    name = "telegram"
    consumes = {InputType.USERNAME}
    admin_only = False

    def available(self, cfg: Settings) -> bool:
        return cfg.telegram_enabled and cfg.browser_scraping_enabled and browser.available()

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        username = _clean_username(value)
        if not username or not _USERNAME_RE.match(username):
            return []

        result = browser.fetch(f"https://t.me/{username}", timeout_ms=15000)
        if result.status == 404:
            return []
        if result.status in {401, 403, 429}:
            raise ConnectorGap(f"telegram returned {result.status} (blocked / rate-limited)")
        if result.status >= 500:
            raise ConnectorGap(f"telegram returned {result.status}")
        if result.status != 200:
            return []
        return _parse_tme_profile(result.text, username)
