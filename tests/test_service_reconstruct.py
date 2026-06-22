"""Reconstructing engine schemas from a flattened Finding row (on-demand path).

The two on-demand actions rebuild a Verdict + cluster from persisted columns.
These exercise the rehydration (enum round-trip, question rebuild, subject) and
the deterministic resolve() on top of it — no DB, no LLM.
"""

from types import SimpleNamespace

from arescope.pipeline.resolution import resolve
from arescope.schemas import (
    ActionBucket,
    Category,
    FixDifficulty,
    InputType,
    JudgedFinding,
    Severity,
)
from arescope.service import _cluster_from_row, _verdict_from_row


def _depends_row():
    """A persisted DEPENDS finding, as the row's columns would hold it."""
    return SimpleNamespace(
        id="finding-1",
        category="credential_exposure",
        severity="high",
        action="depends",
        title="Old password breach",
        problem="Your reused password is in a breach corpus.",
        rationale="Depends on rotation.",
        confidence=0.8,
        fix_difficulty=None,
        easy_fix=None,
        questions=[
            {
                "prompt": "Have you changed this password since the breach?",
                "if_yes": {"severity": "low", "action": "no_action", "note": "already rotated"},
                "if_no": {"severity": "high", "action": "fix_now", "note": "still live"},
            }
        ],
        member_locators=["Old"],
        subject_type="email",
        subject_value="you@x.com",
        remediation=None,
    )


def test_verdict_round_trips_enums_and_questions():
    v = _verdict_from_row(_depends_row())
    assert v.category is Category.CREDENTIAL_EXPOSURE
    assert v.severity is Severity.HIGH
    assert v.action is ActionBucket.DEPENDS
    assert len(v.questions) == 1
    assert v.questions[0].if_no.action is ActionBucket.FIX_NOW
    assert v.problem == "Your reused password is in a breach corpus."


def test_cluster_carries_subject_and_locators():
    c = _cluster_from_row(_depends_row())
    assert c.subject_type is InputType.EMAIL
    assert c.subject_value == "you@x.com"
    assert c.member_locators == ["Old"]


def test_reconstructed_finding_resolves_to_worst_branch():
    row = _depends_row()
    jf = JudgedFinding(verdict=_verdict_from_row(row), cluster=_cluster_from_row(row))
    resolved = resolve(jf, {0: False})
    assert resolved.verdict.action is ActionBucket.FIX_NOW
    assert resolved.verdict.severity is Severity.HIGH
    assert resolved.verdict.questions == []


def test_involved_difficulty_round_trips():
    row = _depends_row()
    row.fix_difficulty = "involved"
    assert _verdict_from_row(row).fix_difficulty is FixDifficulty.INVOLVED
