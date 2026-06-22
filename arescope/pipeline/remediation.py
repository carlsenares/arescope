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
confident of the URL. When the category warrants a formal request (opt-out email,
GDPR/CCPA deletion request, or takedown letter), you may be asked to draft a
complete, ready-to-send artifact in the user's voice, with placeholders like
[YOUR NAME] where personal details are needed. In the artifact, use real line
breaks — never escape them as literal backslash-n. Never include instructions for
attacking anyone."""


def generate_remediation(
    verdict: Verdict, cluster: EvidenceCluster, *, with_artifact: bool = False
) -> Remediation:
    """Generate the tailored fix.

    Advice first (with_artifact=False): guided steps the user can act on, and —
    if the category's track involves a formal request (T1) — a final step telling
    them a ready-to-send letter can be drafted on demand. The artifact itself
    (e.g. a GDPR deletion email) is only written when explicitly asked
    (with_artifact=True), so we never auto-fire a request the user hasn't chosen.
    """
    spec = TAXONOMY[verdict.category]
    tier = spec.default_tier
    artifact_track = tier == RemediationTier.T1_ARTIFACT
    wants_artifact = artifact_track and with_artifact
    cfg = get_settings()

    if wants_artifact:
        instruction = (
            "Produce the steps AND a complete, ready-to-send artifact (the opt-out / "
            "GDPR deletion / takedown request itself)."
        )
    elif artifact_track:
        instruction = (
            "Produce guided steps only — do NOT write the request artifact yet. If "
            "the right fix involves sending a deletion/opt-out/takedown request, say so "
            "in the steps and note that Arescope can draft that request on demand. "
            "Leave artifact null."
        )
    else:
        instruction = "Produce guided steps only (no artifact). Leave artifact null."

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
                    f"{instruction}"
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
