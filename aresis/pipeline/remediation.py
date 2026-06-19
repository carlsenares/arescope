"""Remediation engine: Finding -> fix plan (+ artifact).

P1 ships T0 (guided steps + deep links) for every finding, and T1 (a generated
opt-out / GDPR / deletion artifact) where the category's default tier calls for
it. The tier is decided by the taxonomy (not the LLM); the LLM fills the steps
and, for T1, drafts the artifact. claude-opus-4-8 — remediation is where
reasoning quality matters most (ARCHITECTURE.md §5).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aresis.config import get_settings
from aresis.pipeline.llm import client
from aresis.schemas import (
    Category,
    Evidence,
    Finding,
    Remediation,
    RemediationStep,
    RemediationTier,
)
from aresis.taxonomy import TAXONOMY


class _RemediationDraft(BaseModel):
    """What the LLM fills; tier is fixed by us from the taxonomy."""

    summary: str = Field(description="One or two sentences on what to do and why it helps.")
    steps: list[RemediationStep] = Field(
        description="Concrete, ordered actions with deep links where known."
    )
    artifact: str | None = Field(
        default=None,
        description="For T1 only: the full text of an opt-out / GDPR deletion / takedown "
        "request the user can send. Null for T0.",
    )


_SYSTEM = """You write remediation plans for Aresis, a self-audit privacy tool.
The user owns the exposed identifier. Produce defensive, actionable fixes that
shrink their footprint. Give exact steps with real deep links where you are
confident of the URL. For T1, draft a complete, ready-to-send artifact
(opt-out email, GDPR/CCPA deletion request, or takedown letter) in the user's
voice, with placeholders like [YOUR NAME] where personal details are needed.
In the artifact, use real line breaks — never escape them as literal backslash-n.
Never include instructions for attacking anyone."""


def remediate(finding: Finding, evidence: Evidence) -> Remediation:
    spec = TAXONOMY[finding.category]
    tier = spec.default_tier
    cfg = get_settings()

    wants_artifact = tier in (RemediationTier.T1_ARTIFACT,)
    resp = client().messages.parse(
        model=cfg.remediation_model,
        max_tokens=3000,
        thinking={"type": "adaptive"},
        system=_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Finding: {finding.title}\n"
                    f"Category: {finding.category.value}\n"
                    f"Severity: {finding.severity.value}\n"
                    f"Rationale: {finding.rationale}\n"
                    f"Exposed on: {evidence.locator} "
                    f"(subject {evidence.subject_type.value}: {evidence.subject_value})\n\n"
                    f"Produce a {'T1 (steps + a ready-to-send artifact)' if wants_artifact else 'T0 (guided steps, no artifact)'} "
                    f"remediation plan."
                ),
            }
        ],
        output_format=_RemediationDraft,
    )
    draft = resp.parsed_output
    return Remediation(
        tier=tier,
        summary=draft.summary,
        steps=draft.steps,
        artifact=draft.artifact if wants_artifact else None,
    )


# Categories whose findings always warrant remediation regardless of severity.
_ALWAYS_REMEDIATE: set[Category] = {Category.INFOSTEALER_INFECTION}
