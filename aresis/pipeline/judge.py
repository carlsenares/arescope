"""LLM judge: Evidence -> Finding (category + severity + rationale).

Uses claude-opus-4-8 with structured outputs (the Finding pydantic schema, via
messages.parse) so the result is validated, not parsed (CLAUDE.md / ARCHITECTURE
§5). Adaptive thinking on. The static taxonomy lives in the cached system prefix.
"""

from __future__ import annotations

import json

from aresis.config import get_settings
from aresis.pipeline.llm import client, judge_system_blocks
from aresis.schemas import Evidence, Finding


def _render_evidence(ev: Evidence) -> str:
    raw = [
        {"source": s.source, "kind": s.kind, "locator": s.locator, "raw": s.raw}
        for s in ev.signals
    ]
    return (
        f"Subject ({ev.subject_type.value}): {ev.subject_value}\n"
        f"Kind: {ev.kind}\n"
        f"Locator: {ev.locator}\n"
        f"Corroborating sources: {', '.join(ev.sources)}\n"
        f"Raw signals:\n{json.dumps(raw, indent=2, default=str)}"
    )


def judge(evidence: Evidence) -> Finding:
    cfg = get_settings()
    resp = client().messages.parse(
        model=cfg.judge_model,
        max_tokens=2000,
        thinking={"type": "adaptive"},
        system=judge_system_blocks(),
        messages=[
            {
                "role": "user",
                "content": (
                    "Classify this evidence and assign a severity. "
                    "Be concrete in the rationale about why this severity.\n\n"
                    + _render_evidence(evidence)
                ),
            }
        ],
        output_format=Finding,
    )
    return resp.parsed_output


def judge_all(evidence: list[Evidence]) -> list[tuple[Evidence, Finding]]:
    return [(ev, judge(ev)) for ev in evidence]
