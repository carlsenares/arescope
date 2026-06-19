"""Tier 2 — Opus cluster judge (AI_PIPELINE.md).

Runs only on the escalated head. Produces the full Verdict (category, severity,
action bucket, fix difficulty, inline easy fix, or contingency questions) via
structured output, so the result is validated, not parsed. Adaptive thinking on.
The static taxonomy + verdict contract live in the cached system prefix.
"""

from __future__ import annotations

import json

from aresis.config import get_settings
from aresis.pipeline.llm import client, judge_system_blocks
from aresis.schemas import EvidenceCluster, Verdict


def _render(cluster: EvidenceCluster) -> str:
    # Up to a few representative members' raw, plus the full locator list.
    members = []
    for ev in cluster.members[:8]:
        raw = ev.signals[0].raw if ev.signals else {}
        members.append({"locator": ev.locator, "sources": ev.sources, "raw": raw})
    locs = cluster.member_locators
    loc_line = ", ".join(locs[:60]) + (f", +{len(locs) - 60} more" if len(locs) > 60 else "")
    return (
        f"Suggested category: {cluster.category_hint.value}\n"
        f"Kind: {cluster.kind}\n"
        f"Subject ({cluster.subject_type.value}): {cluster.subject_value}\n"
        f"Cluster size: {len(cluster.members)} item(s)\n"
        f"All locators: {loc_line}\n"
        f"Representative raw (up to 8):\n{json.dumps(members, indent=2, default=str)}"
    )


def judge_cluster(cluster: EvidenceCluster) -> Verdict:
    cfg = get_settings()
    hint = ""
    if cluster.force_escalate and cluster.escalate_reason:
        hint = f"\n\nTier-0 flagged this cluster: {cluster.escalate_reason}"
    resp = client().messages.parse(
        model=cfg.judge_model,
        max_tokens=2500,
        thinking={"type": "adaptive"},
        system=judge_system_blocks(),
        messages=[
            {
                "role": "user",
                "content": (
                    "Judge this evidence cluster as one finding. Treat the whole "
                    "cluster together (e.g. 'in N breaches'), not item by item."
                    + hint
                    + "\n\n"
                    + _render(cluster)
                ),
            }
        ],
        output_format=Verdict,
    )
    return resp.parsed_output
