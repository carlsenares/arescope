"""Telegram username connector parser + graceful browser handling (no network)."""

from __future__ import annotations

import pytest

from arescope.config import Settings
from arescope.connectors.base import ConnectorGap
from arescope.connectors.browser import FetchResult
from arescope.connectors.telegram import TelegramConnector, _parse_tme_profile
from arescope.schemas import InputType


def test_parse_tme_profile_emits_account_and_photo():
    html = """
    <html><head>
      <meta property="og:title" content="Jane Doe">
      <meta property="og:description" content="Contact @janedoe on Telegram">
      <meta property="og:image" content="https://cdn4.telegram-cdn.org/file/jane.jpg">
    </head></html>
    """
    sigs = _parse_tme_profile(html, "janedoe")
    account = next(s for s in sigs if s.kind == "account")
    assert account.raw["url"] == "https://t.me/janedoe"
    assert account.raw["domain"] == "t.me"

    photo = next(s for s in sigs if s.kind == "identity_attribute")
    assert photo.raw["attribute"] == "photo"
    assert photo.raw["value"] == "https://cdn4.telegram-cdn.org/file/jane.jpg"
    assert photo.raw["profile_url"] == "https://t.me/janedoe"
    assert photo.subject_type is InputType.USERNAME


def test_parse_tme_profile_ignores_default_brand_image():
    html = """
    <html><head>
      <meta property="og:title" content="Jane Doe">
      <meta property="og:image" content="https://telegram.org/img/t_logo.png">
    </head></html>
    """
    sigs = _parse_tme_profile(html, "janedoe")
    assert any(s.kind == "account" for s in sigs)
    assert not any(s.kind == "identity_attribute" for s in sigs)


def test_parse_tme_profile_fallback_page_is_clean():
    html = """
    <html><head>
      <title>Telegram Messenger</title>
      <meta property="og:image" content="https://telegram.org/img/telegram_og.png">
    </head></html>
    """
    assert _parse_tme_profile(html, "ghostname") == []


def test_connector_fetches_public_profile(monkeypatch):
    html = """
    <html><head>
      <meta property="og:title" content="Jane Doe">
      <meta property="og:image" content="https://cdn4.telegram-cdn.org/file/jane.jpg">
    </head></html>
    """
    monkeypatch.setattr("arescope.connectors.telegram.browser.available", lambda: True)
    monkeypatch.setattr(
        "arescope.connectors.telegram.browser.fetch",
        lambda *a, **k: FetchResult(status=200, text=html),
    )
    sigs = TelegramConnector().run("@janedoe", InputType.USERNAME, Settings())
    assert any(s.raw.get("attribute") == "photo" for s in sigs)


def test_connector_block_is_gap(monkeypatch):
    monkeypatch.setattr("arescope.connectors.telegram.browser.fetch",
                        lambda *a, **k: FetchResult(status=429, text=""))
    with pytest.raises(ConnectorGap):
        TelegramConnector().run("janedoe", InputType.USERNAME, Settings())


def test_connector_registered():
    from arescope.connectors.registry import REGISTRY

    names = {c.name for c in REGISTRY}
    assert "telegram" in names
