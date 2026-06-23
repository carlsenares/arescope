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
    # With BOTH the paid provider unconfigured AND the free registry disabled, a
    # name-only scan has no source and must surface an honest coverage gap rather
    # than reading as "nothing exposed".
    cfg = Settings(name_search_api_url="", name_search_api_key="", broker_registry_enabled=False,
                   brave_api_key="", urlscan_api_key="")  # Brave + urlscan also consume NAME
    gaps = uncovered_input_gaps([Identifier(type=InputType.NAME, value="Jane Doe")], cfg)
    assert any(g.source == "name lookup" for g in gaps)


def test_name_input_covered_when_provider_configured():
    cfg = Settings(name_search_api_url="https://broker.example/search", name_search_api_key="k")
    gaps = uncovered_input_gaps([Identifier(type=InputType.NAME, value="Jane Doe")], cfg)
    assert not any(g.source == "name lookup" for g in gaps)


def test_name_covered_by_free_broker_registry_by_default():
    # The free, no-key people-search catalog is on by default: a name-only scan is
    # covered (the removal track) without any paid provider.
    cfg = Settings(name_search_api_url="", name_search_api_key="")  # registry default-on
    gaps = uncovered_input_gaps([Identifier(type=InputType.NAME, value="Jane Doe")], cfg)
    assert not any(g.source == "name lookup" for g in gaps)


def test_registry_provider_enumerates_brokers_marked_unconfirmed():
    # The free fallback emits the opt-out catalog with confirmed:false — never an
    # implied "you ARE listed here".
    from arescope.connectors import name as name_mod

    cfg = Settings(name_search_api_url="", name_search_api_key="")  # => registry provider
    signals = name_mod.NameConnector().run("Jane Doe", InputType.NAME, cfg)
    assert len(signals) >= 10  # curated catalog
    assert all(s.kind == "broker_listing" and s.source == "brokers" for s in signals)
    assert all(s.raw["confirmed"] is False for s in signals)
    assert all(s.raw["opt_out_url"] for s in signals)  # every removal target is actionable
    # the CA-registry provenance flag is threaded through
    assert any(s.raw.get("ca_registered") for s in signals)


def test_name_connector_emits_broker_listing_signals(monkeypatch):
    from arescope.connectors import name as name_mod
    from arescope.connectors.name_providers import BrokerListing

    class FakeProvider:
        name = "brokers"

        def available(self, cfg):
            return True

        def search(self, full_name, cfg, *, extended=False):
            assert extended is False  # name-only stays listing-existence
            return [BrokerListing(broker="Spokeo", broker_domain="spokeo.com",
                                  opt_out_url="https://spokeo.com/optout")]

    monkeypatch.setattr(name_mod, "resolve_name_provider", lambda cfg: FakeProvider())
    signals = name_mod.NameConnector().run("Jane Doe", InputType.NAME, Settings())
    assert len(signals) == 1
    s = signals[0]
    assert s.source == "brokers" and s.kind == "broker_listing"
    assert s.subject_type is InputType.NAME and s.locator == "spokeo.com"
    assert s.raw["opt_out_url"] == "https://spokeo.com/optout"
    assert s.raw["has_details"] is False  # no dossier in the normal tier


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
        broker_registry_enabled=False,  # the free name catalog is otherwise on by default
        github_enabled=False,
        reddit_enabled=False,
        gravatar_enabled=False,
        brave_api_key="",  # extended-search keys may be present in the ambient .env
        ghunt_creds_path="",
        # expansion-batch keys are also in the ambient .env — pin off for hermeticity
        leakcheck_api_key="", ipinfo_token="", abuseipdb_api_key="", censys_token="",
        virustotal_api_key="", urlscan_api_key="", ipqs_api_key="", numverify_api_key="",
        # self-hosted tools are default-on + key-less (available when the lib/CLI is
        # present); pin off so the test doesn't depend on what's pip-installed.
        exif_enabled=False, sherlock_enabled=False, ignorant_enabled=False,
    )
    names = {c.name for c in available_connectors(cfg)}
    assert names == {"holehe"}


def test_connectors_declare_consumed_input_types():
    from arescope.connectors.registry import REGISTRY

    for connector in REGISTRY:
        assert connector.consumes
        assert all(isinstance(t, InputType) for t in connector.consumes)
