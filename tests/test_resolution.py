"""Contingency-question resolution — deterministic, free, no LLM."""

from arescope.pipeline.resolution import resolve
from arescope.schemas import (
    ActionBucket,
    Category,
    ContingencyQuestion,
    Evidence,
    EvidenceCluster,
    InputType,
    JudgedFinding,
    Resolution,
    Severity,
    Signal,
    Verdict,
)


def _cluster():
    sig = Signal(source="hibp", kind="breach", locator="Old", subject_value="you@x.com", subject_type=InputType.EMAIL, raw={})
    ev = Evidence(subject_value="you@x.com", subject_type=InputType.EMAIL, kind="breach", locator="Old", sources=["hibp"], signals=[sig])
    return EvidenceCluster(signature="s", category_hint=Category.CREDENTIAL_EXPOSURE, subject_value="you@x.com", subject_type=InputType.EMAIL, kind="breach", members=[ev], member_locators=["Old"])


def _depends_finding():
    q = ContingencyQuestion(
        prompt="Have you changed this password since the breach?",
        if_yes=Resolution(severity=Severity.LOW, action=ActionBucket.NO_ACTION, note="already rotated"),
        if_no=Resolution(severity=Severity.HIGH, action=ActionBucket.FIX_NOW, note="still live; rotate now"),
    )
    v = Verdict(
        category=Category.CREDENTIAL_EXPOSURE, severity=Severity.HIGH, action=ActionBucket.DEPENDS,
        title="Old password breach", rationale="Depends on rotation.", confidence=0.8, questions=[q],
    )
    return JudgedFinding(verdict=v, cluster=_cluster())


def test_yes_resolves_to_low_no_action():
    out = resolve(_depends_finding(), {0: True})
    assert out.verdict.action is ActionBucket.NO_ACTION
    assert out.verdict.severity is Severity.LOW
    assert out.verdict.questions == []
    assert "already rotated" in out.verdict.rationale


def test_no_resolves_to_high_fix_now():
    out = resolve(_depends_finding(), {0: False})
    assert out.verdict.action is ActionBucket.FIX_NOW
    assert out.verdict.severity is Severity.HIGH


def test_unanswered_stays_depends():
    out = resolve(_depends_finding(), {})
    assert out.verdict.action is ActionBucket.DEPENDS
    assert len(out.verdict.questions) == 1


def test_non_depends_finding_untouched():
    jf = _depends_finding()
    jf.verdict.action = ActionBucket.FIX_NOW
    out = resolve(jf, {0: True})
    assert out.verdict.action is ActionBucket.FIX_NOW
