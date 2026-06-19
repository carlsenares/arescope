"""Tier-0 clustering + hard-escalation — deterministic, no LLM/network."""

from datetime import datetime, timezone

from aresis.pipeline.clustering import cluster_evidence
from aresis.schemas import Category, Evidence, InputType, Signal

YEAR = datetime.now(timezone.utc).year


def _ev(kind, locator, raw, value="you@example.com", stype=InputType.EMAIL):
    sig = Signal(source="hibp", kind=kind, locator=locator, subject_value=value, subject_type=stype, raw=raw)
    return Evidence(subject_value=value, subject_type=stype, kind=kind, locator=locator, sources=["hibp"], signals=[sig])


def _breach(name, classes, date):
    return _ev("breach", name, {"data_classes": classes, "breach_date": date})


def test_old_password_breaches_collapse_to_one_cluster():
    evs = [_breach(f"Old{i}", ["Passwords", "Email addresses"], "2012-01-01") for i in range(20)]
    clusters = cluster_evidence(evs)
    assert len(clusters) == 1
    c = clusters[0]
    assert c.category_hint is Category.CREDENTIAL_EXPOSURE
    assert c.force_escalate is True
    assert len(c.members) == 20
    assert len(c.member_locators) == 20


def test_recency_and_salience_split_clusters():
    evs = [
        _breach("OldPw", ["Passwords"], "2010-01-01"),
        _breach("NewPw", ["Passwords"], f"{YEAR}-01-01"),
        _breach("Financial", ["Credit cards"], "2015-01-01"),
        _breach("EmailOnly", ["Email addresses"], "2013-01-01"),
    ]
    clusters = cluster_evidence(evs)
    sigs = {c.signature for c in clusters}
    assert len(clusters) == 4  # all distinct risk profiles
    # email-only is the only one that does not force-escalate
    email_only = next(c for c in clusters if c.member_locators == ["EmailOnly"])
    assert email_only.force_escalate is False
    assert email_only.category_hint is Category.BREACH_MEMBERSHIP


def test_infostealer_always_one_cluster_and_escalates():
    evs = [
        _ev("stealer_log", "RedLine", {"date_compromised": "2026-06-01"}),
        _ev("stealer_log", "LAPTOP-X", {"date_compromised": "2026-06-02"}),
    ]
    clusters = cluster_evidence(evs)
    assert len(clusters) == 1
    assert clusters[0].category_hint is Category.INFOSTEALER_INFECTION
    assert clusters[0].force_escalate is True


def test_accounts_cluster_by_subject_type():
    evs = [
        _ev("account", "Spotify", {}, stype=InputType.EMAIL),
        _ev("account", "GitHub", {}, stype=InputType.EMAIL),
        _ev("account", "Reddit", {}, value="myhandle", stype=InputType.USERNAME),
    ]
    clusters = cluster_evidence(evs)
    cats = {c.category_hint for c in clusters}
    assert cats == {Category.ACCOUNT_FOOTPRINT, Category.USERNAME_CORRELATION}


def test_infra_escalates_on_vuln_or_sensitive_port():
    vuln = _ev("exposed_service", "443/tcp", {"port": 443, "vulns": ["CVE-2021-1234"]}, value="1.2.3.4", stype=InputType.IP)
    rdp = _ev("exposed_service", "3389/tcp", {"port": 3389, "vulns": []}, value="1.2.3.4", stype=InputType.IP)
    benign = _ev("exposed_service", "80/tcp", {"port": 80, "vulns": []}, value="1.2.3.4", stype=InputType.IP)
    clusters = cluster_evidence([vuln, rdp, benign])
    assert len(clusters) == 1  # same IP -> one infra cluster
    assert clusters[0].force_escalate is True  # vuln + RDP present
