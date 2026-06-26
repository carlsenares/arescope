"""Exposure-map builder pure logic: convergence keys, masking, severity merge."""

from types import SimpleNamespace

from arescope.graph import (
    _classify,
    _domain,
    _mask,
    _merge_node_data,
    _platform_key,
    _slug,
    _worse,
)


def _sig(source, kind, locator, raw):
    return SimpleNamespace(source=source, kind=kind, locator=locator, raw=raw)


def test_domain_normalizes():
    assert _domain("https://www.twitter.com/jack") == "twitter.com"
    assert _domain("http://GitHub.com") == "github.com"
    assert _domain(None) is None


def test_platform_key_converges_holehe_and_maigret():
    # Holehe carries a domain; Maigret carries a url — both must map to one key
    # so an email and a username on the same site collapse to ONE node.
    holehe = _sig("holehe", "account", "twitter", {"domain": "twitter.com"})
    maigret = _sig("maigret", "account", "Twitter", {"url": "https://twitter.com/x"})
    assert _platform_key(holehe) == _platform_key(maigret) == "twitter.com"


def test_classify_site_nodes_share_id():
    a = _classify(_sig("holehe", "account", "twitter", {"domain": "twitter.com"}))
    b = _classify(_sig("maigret", "account", "Twitter", {"url": "https://twitter.com/x"}))
    assert a[0] == b[0] == "site:twitter.com"  # same node id => convergence


def test_classify_breach_and_service():
    breach = _classify(_sig("hibp", "breach", "Adobe", {"title": "Adobe", "data_classes": ["Passwords"]}))
    assert breach[0] == "breach:Adobe" and breach[1]["type"] == "breach"
    svc = _classify(_sig("shodan", "exposed_service", "22/tcp", {"port": 22, "vulns": ["CVE-1"]}))
    assert svc[0] == "svc:22/tcp" and svc[1]["type"] == "service"


def test_classify_broker_listing_node():
    b = _classify(_sig("brokers", "broker_listing", "spokeo.com",
                       {"broker": "Spokeo", "domain": "spokeo.com",
                        "opt_out_url": "https://spokeo.com/optout"}))
    assert b[0] == "broker:spokeo.com" and b[1]["type"] == "broker"
    assert b[1]["label"] == "Spokeo"
    assert b[1]["meta"]["opt_out_url"] == "https://spokeo.com/optout"


def test_classify_web_mention_node():
    m = _classify(_sig("tavily", "web_mention", "https://news.site/jane",
                       {"title": "Jane in the news", "url": "https://news.site/jane",
                        "domain": "news.site"}))
    assert m[0].startswith("mention:") and m[1]["type"] == "mention"
    assert m[1]["label"] == "Jane in the news"
    assert m[1]["meta"]["domain"] == "news.site"
    assert m[1]["meta"]["source"] == "Web search"  # derived from sig.source=tavily
    # same URL from another source converges to one node
    again = _classify(_sig("brave", "web_mention", "https://news.site/jane",
                           {"url": "https://news.site/jane", "domain": "news.site"}))
    assert again[0] == m[0]


def test_classify_iploc_from_any_host_profile_source():
    # IPinfo (not just Shodan) host_profile must produce the IP-location node.
    n = _classify(_sig("ipinfo", "host_profile", "8.8.8.8",
                       {"location": "Cologne, DE", "isp": "Example ISP"}))
    assert n[0] == "iploc:8.8.8.8" and n[1]["type"] == "iploc"
    assert n[1]["label"] == "Cologne, DE"


def test_iploc_source_without_location_does_not_clobber():
    # AbuseIPDB has no `location`; merging it after IPinfo must NOT blank the city,
    # and a host_profile with no location classifies to label=None (flatten fills it).
    ipinfo = _classify(_sig("ipinfo", "host_profile", "8.8.8.8",
                            {"location": "Cologne, DE", "isp": "Example ISP"}))
    abuse = _classify(_sig("abuseipdb", "host_profile", "8.8.8.8",
                           {"isp": "Example ISP", "abuse_score": 0}))
    assert abuse[1]["label"] is None  # no location => no clobbering label
    # simulate the merge order ipinfo-then-abuse on one node's data
    data = dict(ipinfo[1])
    data["meta"] = dict(ipinfo[1]["meta"])
    _merge_node_data(data, abuse[1])
    assert data["label"] == "Cologne, DE"          # city survives the merge
    assert data["meta"]["location"] == "Cologne, DE"  # not blanked by the source w/o location


def test_present_humanizes_nodes():
    from arescope.graph import _present
    # broker: unconfirmed listings are collapsed into a removal-checklist node (count/items)
    assert "none confirmed" in _present(
        {"type": "broker", "meta": {"confirmed": False, "count": 5, "items": []}}).lower()
    # a CONFIRMED individual listing still reads as a real people-search hit
    assert _present({"type": "broker", "meta": {"confirmed": True}}).startswith("People-search")
    # intelx collapsed node + a default avatar
    assert "leaked" in _present({"type": "mention", "id": "intelx:in:ip:1.1.1.1", "meta": {}})
    assert _present({"type": "photo", "meta": {"is_default": True}}) is None
    assert _present({"type": "photo", "meta": {}}).startswith("Your real photo")


def test_directory_noise_filter():
    from arescope.connectors._webfilter import is_directory_noise
    # the exact case from the test report: a LinkedIn directory of many same-named people
    assert is_directory_noise("https://www.linkedin.com/pub/dir/x", "50+ Breeck profiles | LinkedIn")
    assert is_directory_noise("https://spokeo.com/John-Breeck")            # aggregator domain
    assert is_directory_noise("https://any.site/p", "127+ profiles named Breeck")  # title rule
    # a real profile / personal page is kept
    assert not is_directory_noise("https://www.linkedin.com/in/john-breeck-123", "John Breeck | LinkedIn")
    assert not is_directory_noise("https://janedoe.com/about", "About Jane Doe")


def test_slug_override():
    assert _slug("twitter.com") == "x"
    assert _slug("github.com") == "github"


def test_mask():
    assert _mask("breeckpatrik@gmail.com", "email").endswith("@gmail.com")
    assert _mask("breeckpatrik@gmail.com", "email").startswith("b")
    assert _mask("alexsmith", "username") == "al" + "•" * 7


def test_worse_picks_higher_severity():
    assert _worse("low", "critical") == "critical"
    assert _worse("high", "low") == "high"
    assert _worse(None, "medium") == "medium"


def test_map_severity_heuristic():
    # Map mode colours nodes without the LLM: kind-based, with a few raw refinements.
    from arescope.graph import _map_sev
    assert _map_sev(_sig("hudsonrock", "stealer_log", "x", {})) == "critical"
    assert _map_sev(_sig("leakcheck", "breach", "X", {"password_exposed": True})) == "high"
    # a bare membership (no password, no classes) softens to low
    assert _map_sev(_sig("leakcheck", "breach", "X", {})) == "low"
    assert _map_sev(_sig("ipinfo", "host_profile", "1.1.1.1", {})) == "low"
    # an abused IP escalates
    assert _map_sev(_sig("abuseipdb", "host_profile", "1.1.1.1", {"abuse_score": 80})) == "high"
    assert _map_sev(_sig("ipqs", "phone_risk", "x", {"recent_abuse": True})) == "high"
    assert _map_sev(_sig("urlscan", "web_mention", "x", {})) == "info"
