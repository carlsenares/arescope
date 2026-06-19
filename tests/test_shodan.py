"""Shodan connector gating + signal shape (no network)."""

from aresis.config import Settings
from aresis.connectors.shodan import ShodanConnector
from aresis.schemas import InputType


def test_shodan_unavailable_without_key():
    assert ShodanConnector().available(Settings(shodan_api_key="")) is False


def test_shodan_available_with_key():
    assert ShodanConnector().available(Settings(shodan_api_key="deadbeef")) is True


def test_shodan_consumes_ip_only():
    assert ShodanConnector().consumes == {InputType.IP}


def test_shodan_registered():
    from aresis.connectors.registry import REGISTRY

    assert any(c.name == "shodan" for c in REGISTRY)
