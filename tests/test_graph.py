"""Exposure-map builder pure logic: convergence keys, masking, severity merge."""

from types import SimpleNamespace

from arescope.graph import _classify, _domain, _mask, _platform_key, _slug, _worse


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
