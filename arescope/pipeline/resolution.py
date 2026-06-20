"""Resolve a DEPENDS finding from user answers — deterministic and free.

The judge precomputed both branches of every yes/no question, so applying the
answers needs no second LLM call (AI_PIPELINE.md). With multiple questions we
resolve conservatively to the worst-case branch among the answers given.
"""

from __future__ import annotations

from arescope.schemas import (
    SEVERITY_ORDER,
    ActionBucket,
    JudgedFinding,
    Resolution,
)


def resolve(jf: JudgedFinding, answers: dict[int, bool]) -> JudgedFinding:
    """answers maps question index -> yes(True)/no(False). Unanswered => unchanged."""
    v = jf.verdict
    if v.action is not ActionBucket.DEPENDS or not v.questions:
        return jf

    chosen: list[Resolution] = []
    for i, q in enumerate(v.questions):
        if i in answers:
            chosen.append(q.if_yes if answers[i] else q.if_no)
    if not chosen:
        return jf  # still contingent

    worst = max(chosen, key=lambda r: SEVERITY_ORDER[r.severity])
    note = worst.note or "resolved from your answers"
    resolved = v.model_copy(
        update={
            "severity": worst.severity,
            "action": worst.action,
            "rationale": f"{v.rationale}\n\nResolved from your answers: {note}",
            "questions": [],
        }
    )
    return jf.model_copy(update={"verdict": resolved})
