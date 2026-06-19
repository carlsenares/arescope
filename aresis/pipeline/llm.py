"""Shared Anthropic client + the cached taxonomy system prompt.

The taxonomy rubric is large and identical across every judge call in a scan, so
it goes first in the system prompt behind a cache_control breakpoint
(ARCHITECTURE.md §5 — prompt-cache the static taxonomy). The variable evidence
goes in the user turn, after the cached prefix.
"""

from __future__ import annotations

from functools import lru_cache

import anthropic

from aresis.taxonomy import taxonomy_prompt_block


@lru_cache
def client() -> anthropic.Anthropic:
    # Reads ANTHROPIC_API_KEY from the environment.
    return anthropic.Anthropic()


JUDGE_SYSTEM = f"""You are the severity judge for Aresis, a personal exposure scanner.
For each piece of evidence about identifiers the operator OWNS, classify it into
exactly one finding category and assign a severity, scoring four dimensions:
takeover potential, data sensitivity, recency, and exploitability.

Severity levels:
- critical: enables account takeover or device compromise right now.
- high: strong attack enabler; fixable but urgent.
- medium: privacy/footprint exposure enabling targeted attacks.
- low: minor footprint, low actionability.
- info: neutral context, no action needed.

This is a SELF-AUDIT tool. Frame the title and rationale as defensive guidance to
the owner shrinking their footprint — never as how to attack someone.

{taxonomy_prompt_block()}"""


def judge_system_blocks() -> list[dict]:
    """System prompt as a single cached text block."""
    return [{"type": "text", "text": JUDGE_SYSTEM, "cache_control": {"type": "ephemeral"}}]
