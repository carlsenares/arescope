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
