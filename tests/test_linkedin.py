"""LinkedIn extraction parsers (pure — no network)."""

from __future__ import annotations

from arescope.config import Settings
from arescope.connectors.linkedin import (
    _parse_apify_linkedin,
    _parse_jina,
    apify_linkedin_available,
    fetch_via_apify,
    jina_available,
)
from arescope.schemas import InputType

_JINA_MD = """Title: Jane Doe - Senior Product Manager - Acme Corp | LinkedIn
URL Source: https://www.linkedin.com/in/janedoe
Markdown Content:
Jane Doe is a product manager based in Cologne with 10 years of experience.
"""


def test_parse_jina_pulls_name_and_headline():
    p = _parse_jina(_JINA_MD, "https://www.linkedin.com/in/janedoe")
    assert p["name"] == "Jane Doe"
    assert p["headline"] == "Senior Product Manager - Acme Corp"
    assert "product manager" in (p["snippet"] or "")
    assert "Title:" not in (p["snippet"] or "")  # header stripped


def test_parse_jina_handles_bare_title():
    p = _parse_jina("Title: Jane Doe | LinkedIn\nMarkdown Content:\nhi", "u")
    assert p["name"] == "Jane Doe" and p["headline"] is None


def test_parse_jina_empty_is_safe():
    p = _parse_jina("", "u")
    assert p["name"] is None and p["headline"] is None


def test_parse_apify_linkedin_fields():
    p = _parse_apify_linkedin(
        {"fullName": "Jane Doe", "headline": "PM @ Acme",
         "addressWithCountry": "Cologne, Germany", "companyName": "Acme",
         "profilePic": "https://media.licdn.com/jane.jpg"},
        "https://linkedin.com/in/janedoe")
    assert p["name"] == "Jane Doe"
    assert p["location"] == "Cologne, Germany"
    assert p["company"] == "Acme"
    assert p["photo"].endswith("jane.jpg")


def test_availability_flags():
    assert jina_available(Settings(jina_enabled=True)) is True
    assert jina_available(Settings(jina_enabled=False)) is False
    assert apify_linkedin_available(Settings(apify_token="", apify_linkedin_actor="x")) is False
    assert apify_linkedin_available(Settings(apify_token="t", apify_linkedin_actor="a/b")) is True


def test_is_linkedin_url_rejects_lookalikes():
    from arescope.service import _is_linkedin_url
    assert _is_linkedin_url("https://www.linkedin.com/in/jane")
    assert _is_linkedin_url("https://linkedin.com/in/jane")
    assert _is_linkedin_url("https://de.linkedin.com/in/jane")
    assert not _is_linkedin_url("https://evil-linkedin.com/in/jane")
    assert not _is_linkedin_url("https://linkedin.com.attacker.io/in/jane")
    assert not _is_linkedin_url("not a url")


def test_apify_empty_items_is_clean(monkeypatch):
    import arescope.connectors.linkedin as lk

    class _Resp:
        status_code = 200

        def json(self):
            return []

    monkeypatch.setattr(lk.httpx, "post", lambda *a, **k: _Resp())
    out = fetch_via_apify("https://linkedin.com/in/x",
                          Settings(apify_token="t", apify_linkedin_actor="a/b"),
                          "e@x.com", InputType.EMAIL)
    assert out == []
