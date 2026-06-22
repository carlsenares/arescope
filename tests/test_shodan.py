"""Shodan connector gating + signal shape (no network)."""

from arescope.config import Settings
from arescope.connectors.shodan import ShodanConnector
from arescope.schemas import InputType


def test_shodan_unavailable_without_key():
    assert ShodanConnector().available(Settings(shodan_api_key="")) is False


def test_shodan_available_with_key():
    assert ShodanConnector().available(Settings(shodan_api_key="deadbeef")) is True


def test_shodan_consumes_ip_only():
    assert ShodanConnector().consumes == {InputType.IP}


def test_shodan_registered():
    from arescope.connectors.registry import REGISTRY

    assert any(c.name == "shodan" for c in REGISTRY)


def test_shodan_emits_host_profile_and_services(monkeypatch):
    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "city": "Berlin", "region_code": "BE", "country_name": "Germany",
                "country_code": "DE", "latitude": 52.5, "longitude": 13.4,
                "isp": "Deutsche Telekom", "org": "DT", "asn": "AS3320",
                "hostnames": ["host.example.de"], "domains": ["example.de"],
                "ports": [80, 443], "tags": ["cloud"], "vulns": [],
                "data": [{"port": 443, "transport": "tcp", "product": "nginx", "vulns": {}}],
            }

    monkeypatch.setattr("arescope.connectors.shodan.httpx.get", lambda *a, **k: FakeResp())
    sigs = ShodanConnector().run("203.0.113.4", InputType.IP, Settings(shodan_api_key="x"))
    kinds = [s.kind for s in sigs]
    assert "host_profile" in kinds and "exposed_service" in kinds
    hp = next(s for s in sigs if s.kind == "host_profile")
    assert "Berlin" in hp.raw["location"] and hp.raw["isp"] == "Deutsche Telekom"
    assert hp.raw["open_ports"] == [80, 443]
