"""Tier 1 — Haiku batch triage (AI_PIPELINE.md), the recall net.

Every cluster (100%) gets a cheap provisional severity + an escalate decision in
ONE batched Haiku call. Clusters that are force-escalated by Tier 0 or flagged
here go to the Opus judge; the rest carry their Haiku label into the rolled-up
report tail. Bias is toward escalation — missing a real risk is the only
unacceptable failure.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from arescope.config import get_settings
from arescope.pipeline.llm import client, triage_system_blocks
from arescope.schemas import EvidenceCluster, Severity


class TriageItem(BaseModel):
    id: int
    severity: Severity
    escalate: bool
    reason: str


class _TriageBatch(BaseModel):
    items: list[TriageItem]


def _render(idx: int, c: EvidenceCluster) -> str:
    sample = c.members[0].signals[0].raw if c.members and c.members[0].signals else {}
    locs = ", ".join(c.member_locators[:12])
    if len(c.member_locators) > 12:
        locs += f", +{len(c.member_locators) - 12} more"
    return (
        f"[{idx}] category_hint={c.category_hint.value} kind={c.kind} "
        f"members={len(c.members)}\n"
        f"     subject ({c.subject_type.value}): {c.subject_value}\n"
        f"     locators: {locs}\n"
        f"     sample raw: {json.dumps(sample, default=str)[:400]}"
    )


def triage_clusters(clusters: list[EvidenceCluster]) -> dict[int, TriageItem]:
    if not clusters:
        return {}
    body = "\n".join(_render(i, c) for i, c in enumerate(clusters))
    cfg = get_settings()
    resp = client().messages.parse(
        model=cfg.triage_model,
        max_tokens=2000,
        system=triage_system_blocks(),
        messages=[
            {
                "role": "user",
                "content": (
                    "Triage each cluster. Return exactly one item per id.\n\n" + body
                ),
            }
        ],
        output_format=_TriageBatch,
    )
    out = {it.id: it for it in resp.parsed_output.items}
    # Safety: any cluster the model skipped is escalated, never dropped.
    for i in range(len(clusters)):
        out.setdefault(
            i, TriageItem(id=i, severity=Severity.MEDIUM, escalate=True, reason="not triaged — escalated by default")
        )
    return out
