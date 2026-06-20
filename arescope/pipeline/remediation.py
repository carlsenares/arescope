"""On-demand remediation (AI_PIPELINE.md): the INVOLVED tailored fix / artifact.

Easy fixes are already inline in the verdict (`easy_fix`) — no call needed. This
generates the tailored plan + artifact for an *involved* finding when the user
asks for it, which is the natural paywall point. The tier is decided by the
taxonomy; the LLM fills the steps and, for T1, drafts the artifact.
claude-opus-4-8 — remediation is where reasoning quality matters most.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from arescope.config import get_settings
from arescope.pipeline.llm import client
from arescope.schemas import (
    EvidenceCluster,
    Remediation,
    RemediationStep,
    RemediationTier,
    Verdict,
)
from arescope.taxonomy import TAXONOMY


class _Draft(BaseModel):
    summary: str = Field(description="One or two sentences: what to do and why it helps.")
    steps: list[RemediationStep] = Field(description="Concrete, ordered actions with deep links.")
    artifact: str | None = Field(
        default=None,
        description="For T1 only: full text of an opt-out / GDPR deletion / takedown request. "
        "Null for T0.",
    )


_SYSTEM = """You write remediation plans for Arescope, a self-audit privacy tool.
The user owns the exposed identifier. Produce defensive, actionable fixes that
shrink their footprint, with exact steps and real deep links where you are
confident of the URL. For T1, draft a complete, ready-to-send artifact (opt-out
email, GDPR/CCPA deletion request, or takedown letter) in the user's voice, with
placeholders like [YOUR NAME] where personal details are needed. In the artifact,
use real line breaks — never escape them as literal backslash-n. Never include
instructions for attacking anyone."""


def generate_remediation(verdict: Verdict, cluster: EvidenceCluster) -> Remediation:
    spec = TAXONOMY[verdict.category]
    tier = spec.default_tier
    wants_artifact = tier == RemediationTier.T1_ARTIFACT
    cfg = get_settings()

    locs = ", ".join(cluster.member_locators[:40])
    resp = client().messages.parse(
        model=cfg.remediation_model,
        max_tokens=3000,
        thinking={"type": "adaptive"},
        system=_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Finding: {verdict.title}\n"
                    f"Category: {verdict.category.value}\n"
                    f"Severity: {verdict.severity.value}\n"
                    f"Rationale: {verdict.rationale}\n"
                    f"Exposed on: {locs} "
                    f"(subject {cluster.subject_type.value}: {cluster.subject_value})\n\n"
                    f"Produce a {'T1 (steps + a ready-to-send artifact)' if wants_artifact else 'T0 (guided steps, no artifact)'} "
                    f"remediation plan."
                ),
            }
        ],
        output_format=_Draft,
    )
    draft = resp.parsed_output
    return Remediation(
        tier=tier,
        summary=draft.summary,
        steps=draft.steps,
        artifact=draft.artifact if wants_artifact else None,
    )
