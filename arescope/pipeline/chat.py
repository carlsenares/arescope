"""Ask-Opus chat — answer a user's question about a finding or their exposure map.

A small conversational layer over the same Opus model used for judging. Stateless
per call: the caller passes the context (the finding's verdict + raw signals, or
the map's structure) and the prior turns; we return the assistant's reply text.
Persistence of the thread lives in service.py. Plain text out — not structured —
so this uses messages.create (consulted the claude-api skill for the SDK shape).
"""

from __future__ import annotations

from arescope.config import get_settings
from arescope.pipeline.llm import client

_SYSTEM = """You are Opus, the analyst inside Arescope — a personal, self-audit
exposure scanner. You are talking to the OWNER of the data about THEIR OWN
exposure. Your job is to help them understand a finding (or their exposure map)
and decide what to do about it.

- Answer in plain language, concise (a few sentences; short list if it helps).
- Ground every answer in the context provided below — if it doesn't contain the
  answer, say so plainly rather than guessing.
- This is defensive: frame everything as how the owner protects themselves. Never
  explain how to attack or track anyone else.
- When they ask "is this mine / how do I know", walk them through what in the raw
  data would tell them (e.g. a stealer log's machine name vs. their own devices),
  and be honest about what can't be known for certain."""


def answer(context: str, history: list[dict], question: str) -> str:
    """Generate a reply. `history` is prior turns [{role, content}, ...]."""
    cfg = get_settings()
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": question})
    resp = client().messages.create(
        model=cfg.judge_model,
        max_tokens=1200,
        thinking={"type": "adaptive"},
        system=f"{_SYSTEM}\n\n--- CONTEXT ---\n{context}",
        messages=messages,
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
