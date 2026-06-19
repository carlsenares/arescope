"""Normalizer dedup behaviour — pure code, no keys/network."""

from aresis.pipeline.normalizer import normalize
from aresis.schemas import InputType, Signal


def _sig(source: str, kind: str, locator: str, value: str = "you@example.com") -> Signal:
    return Signal(
        source=source,
        kind=kind,
        locator=locator,
        subject_value=value,
        subject_type=InputType.EMAIL,
    )


def test_cross_source_signals_merge_into_one_evidence():
    signals = [
        _sig("holehe", "account", "Spotify"),
        _sig("maigret", "account", "spotify"),  # same locator, different case
    ]
    evidence = normalize(signals)
    assert len(evidence) == 1
    assert evidence[0].sources == ["holehe", "maigret"]
    assert len(evidence[0].signals) == 2


def test_distinct_locators_stay_separate():
    signals = [
        _sig("hibp", "breach", "Adobe"),
        _sig("hibp", "breach", "LinkedIn"),
    ]
    evidence = normalize(signals)
    assert len(evidence) == 2


def test_locator_preserves_original_casing():
    evidence = normalize([_sig("holehe", "account", "GitHub")])
    assert evidence[0].locator == "GitHub"
