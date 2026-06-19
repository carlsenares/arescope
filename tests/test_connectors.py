"""Connector gating + graceful degradation — the hard rule (ARCHITECTURE §4.5)."""

from aresis.config import Settings
from aresis.connectors.hibp import HIBPConnector
from aresis.connectors.registry import available_connectors
from aresis.schemas import InputType


def test_hibp_unavailable_without_key():
    cfg = Settings(hibp_api_key="")
    assert HIBPConnector().available(cfg) is False


def test_hibp_available_with_key():
    cfg = Settings(hibp_api_key="deadbeef")
    assert HIBPConnector().available(cfg) is True


def test_available_connectors_respects_toggles():
    # Explicit about every gating field so the test is hermetic — Settings()
    # otherwise inherits ambient .env values (HIBP/Shodan keys, etc.).
    cfg = Settings(
        hibp_api_key="",
        hudsonrock_enabled=False,
        holehe_enabled=True,
        maigret_enabled=False,
        shodan_api_key="",
    )
    names = {c.name for c in available_connectors(cfg)}
    assert names == {"holehe"}


def test_connectors_declare_consumed_input_types():
    from aresis.connectors.registry import REGISTRY

    for connector in REGISTRY:
        assert connector.consumes
        assert all(isinstance(t, InputType) for t in connector.consumes)
