"""Opus Evaluate — digest builder + the parse call (Opus client mocked)."""

from __future__ import annotations

from types import SimpleNamespace

import arescope.pipeline.evaluate as ev
from arescope.schemas import DerivedFact, MapEvaluation, ProfileSection


def _sig(source, kind, locator, raw):
    return SimpleNamespace(source=source, kind=kind, locator=locator, raw=raw)


_SIGNALS = [
    _sig("github", "account", "github.com", {
        "domain": "github.com", "display_name": "Jane Doe",
        "languages": ["Python", "Rust"], "topics": ["osint"],
        "top_repos": [{"name": "aresis", "language": "Python", "description": "self-audit"}]}),
    _sig("instagram_web", "account", "instagram.com", {
        "domain": "instagram.com", "recent_posts": ["morning espresso in Cologne"]}),
    _sig("ghunt", "identity_attribute", "g:location", {
        "attribute": "location", "value": "Cologne, Germany", "platform": "google maps"}),
    _sig("hibp", "breach", "Adobe", {"title": "Adobe"}),
]


def test_digest_includes_platforms_attrs_and_breach_count():
    d = ev._digest(_SIGNALS, "this person")
    assert "github.com" in d and "instagram.com" in d
    assert "Python" in d and "aresis" in d            # repo/language detail
    assert "morning espresso" in d                     # post text
    assert "Cologne" in d                              # identity attribute
    assert "1 breach record" in d                      # security exposure rollup


def test_digest_empty_is_safe():
    d = ev._digest([], "this person")
    assert "Subject: this person" in d


def test_evaluate_map_uses_structured_output(monkeypatch):
    fake = MapEvaluation(
        headline="You give away a lot.",
        exposure_level="significant",
        derived_facts=[DerivedFact(statement="Lives in Cologne", category="location",
                                   confidence="high", evidence=["Maps", "Instagram"],
                                   map_node=True)],
        profile=[ProfileSection(heading="Who", points=["A developer."])],
        most_revealing=["Google Maps reviews"],
    )
    captured = {}

    class _Msgs:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(parsed_output=fake)

    monkeypatch.setattr(ev, "client", lambda: SimpleNamespace(messages=_Msgs()))
    out = ev.evaluate_map(_SIGNALS, label="this person")

    assert out is fake
    assert captured["output_format"] is MapEvaluation       # structured, not text-parsed
    assert "github.com" in captured["messages"][0]["content"]  # digest reached the prompt
