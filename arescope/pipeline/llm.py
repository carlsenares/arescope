"""Shared Anthropic client + the cached taxonomy system prompt.

The taxonomy rubric is large and identical across every judge call in a scan, so
it goes first in the system prompt behind a cache_control breakpoint
(ARCHITECTURE.md §5 — prompt-cache the static taxonomy). The variable evidence
goes in the user turn, after the cached prefix.
"""

from __future__ import annotations

from functools import lru_cache

import anthropic

from arescope.taxonomy import taxonomy_prompt_block


@lru_cache
def client() -> anthropic.Anthropic:
    # Reads ANTHROPIC_API_KEY from the environment.
    return anthropic.Anthropic()


_SEVERITY = """Severity levels:
- critical: enables account takeover or device compromise right now.
- high: strong attack enabler; fixable but urgent.
- medium: privacy/footprint exposure enabling targeted attacks.
- low: minor footprint, low actionability.
- info: neutral context, no action needed."""

JUDGE_SYSTEM = f"""You are the severity judge for Arescope, a personal exposure scanner.
You judge a CLUSTER of related evidence about identifiers the operator OWNS
(e.g. many breaches sharing a risk profile) as ONE finding. Score four
dimensions: takeover potential, data sensitivity, recency, exploitability.

{_SEVERITY}

Output via the structured schema:
- title: a short, specific headline (e.g. "Password exposed in the Adobe breach").
- problem: ONE line stating the concrete issue — what is exposed and the risk it
  creates. No preamble, no fix. (e.g. "Your email and a reused password were leaked
  and are circulating in credential-stuffing lists.")
- rationale: 2-4 sentences explaining what it means for the owner and why the
  severity is what it is — the context behind the score. Keep problem and rationale
  distinct: problem = WHAT, rationale = WHY IT MATTERS. Plain language, no jargon walls.
- category + severity (rubric below).
- action: fix_now (dangerous regardless of context) | worth_fixing (should
  probably act; minor context dependence) | depends (severity genuinely hinges
  on facts you don't have) | no_action (info/low).
- For fix_now / worth_fixing set fix_difficulty:
    easy     -> the fix is universally known (change the password, enable 2FA,
                close the port). PUT the one-line fix in easy_fix. Recognising
                it's easy means you already know the fix, so write it — never
                withhold an easy fix to upsell; that's user-hostile.
    involved -> needs tailoring or a generated artifact (GDPR/opt-out letter,
                infostealer recovery playbook). Leave easy_fix null; the tailored
                fix is generated later, on demand.
- For action=depends: do NOT propose a fix. Emit the FEWEST yes/no questions
  whose answers resolve the severity, each with both branches filled
  (if_yes / if_no -> severity + action + short note). Only ask when the answer
  changes the outcome — never when it's bad either way or fine either way. One
  decisive question beats three weak ones.

Infostealer infections: if the harvested credential is genuinely the owner's,
this is NEVER below high — the infected machine's saved credentials were stolen
and must be rotated. The split between critical and high is WHOSE machine was
infected (a stealer log is tied to a machine; the owner's email appears because
that machine held their saved login), not whether the email is theirs. When
severity hinges on it, ask one question — "Is <machine> one of your devices?":
yes -> critical (full device compromise: reimage, rotate everything, revoke all
sessions, since stolen cookies bypass 2FA); no -> high (your credential sat on
someone else's infected machine: rotate it and revoke its sessions, no reimage of
your hardware). Only go below high if the data looks like a mislabeled combolist
rather than a genuine stealer log.

This is a SELF-AUDIT tool. Frame everything as defensive guidance to the owner —
never as how to attack someone.

{taxonomy_prompt_block()}"""

TRIAGE_SYSTEM = f"""You are the fast triage layer for Arescope, a self-audit exposure
scanner. For each evidence cluster, assign a provisional severity and decide
whether it needs a deeper look. Bias HARD toward escalation: if a cluster might
be medium or worse, or its true severity depends on context you can't see, set
escalate=true. Missing a real risk is far worse than escalating a harmless one.
Be terse.

{_SEVERITY}

{taxonomy_prompt_block()}"""


def _cached(text: str) -> list[dict]:
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def judge_system_blocks() -> list[dict]:
    return _cached(JUDGE_SYSTEM)


def triage_system_blocks() -> list[dict]:
    return _cached(TRIAGE_SYSTEM)
