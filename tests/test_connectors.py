"""Connector gating + graceful degradation — the hard rule (ARCHITECTURE §4.5)."""

from arescope.config import Settings
from arescope.connectors.hibp import HIBPConnector
from arescope.connectors.registry import available_connectors
from arescope.pipeline.orchestrator import uncovered_input_gaps
from arescope.schemas import Identifier, InputType


def test_hibp_unavailable_without_key():
    cfg = Settings(hibp_api_key="")
    assert HIBPConnector().available(cfg) is False


def test_hibp_available_with_key():
    cfg = Settings(hibp_api_key="deadbeef")
    assert HIBPConnector().available(cfg) is True


def test_name_input_reported_as_uncovered_gap():
    # No connector consumes a name, so a name-only scan must surface an honest
    # coverage gap rather than silently reading as "nothing exposed".
    cfg = Settings()
    gaps = uncovered_input_gaps([Identifier(type=InputType.NAME, value="Jane Doe")], cfg)
    assert any(g.source == "name lookup" for g in gaps)


def test_email_input_is_covered_no_gap():
    cfg = Settings(hibp_api_key="deadbeef")  # at least one email connector available
    gaps = uncovered_input_gaps([Identifier(type=InputType.EMAIL, value="a@b.com")], cfg)
    assert not any(g.source == "email lookup" for g in gaps)


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
    from arescope.connectors.registry import REGISTRY

    for connector in REGISTRY:
        assert connector.consumes
        assert all(isinstance(t, InputType) for t in connector.consumes)
