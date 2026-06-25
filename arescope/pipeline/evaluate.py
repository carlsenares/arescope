"""Opus Evaluate — the inference layer over the assembled identity map (GRAPH.md §13).

The map's whole point is the *shock*: from easy public seeds, how much can be inferred?
Collection lands the raw footprint (accounts, posts, reviews, repos, breaches, mentions);
this step hands Opus the WHOLE digest once and asks it to deduce as much as it reasonably
can — then splits its answer into (a) `derived_facts` (some become map nodes) and (b) a
prose `profile` the owner reads. On-demand only (one Opus call), never per node.

Self-audit framing: everything is "what someone could infer about YOU", shown to you.
"""

from __future__ import annotations


from arescope.config import get_settings
from arescope.pipeline.llm import _cached, client
from arescope.schemas import MapEvaluation

EVALUATE_SYSTEM = """You are the Evaluate step of Arescope, a personal exposure scanner.
You are given the ASSEMBLED PUBLIC FOOTPRINT of a person who is auditing THEMSELVES —
everything here was found from identifiers they own (their email, username, phone, name).
Your job: infer as much as you reasonably can about who this person is, so they SEE how
much the open internet gives away about them "just from knowing where to look".

Reason like a careful analyst, strictly from the evidence. Specific pointers:
- Registered platforms (email/username accounts): what someone USES reveals what they do
  and care about — dev tools => technical; dating/fitness/finance apps => lifestyle; niche
  forums => hobbies/communities.
- Google Maps reviews / tagged post locations: cluster them — repeated city => likely home
  city; cuisines/venues => tastes; gym/commute patterns => routine.
- Instagram / social posts: topics, people, places, lifestyle, what they broadcast.
- LinkedIn: employer, role, seniority, career history, location.
- GitHub repos/languages/topics: technical profile, possibly employer or domain.
- Breaches / stealer logs: security exposure, password reuse, what's circulating.
- Convergence: facts corroborated by SEVERAL independent sources are higher-confidence.

Rules:
- Be evidence-bound. Never invent. Mark confidence honestly (low/medium/high). If the
  footprint is thin, say so and infer little — do not pad.
- Split your output: a fact concrete enough to pin (a place, a job, a city, a real name)
  gets map_node=true; a characterisation ("comfortable being public", "active at night")
  is profile-only (map_node=false).
- profile = the narrative the owner reads: a few sections (who they are, what they do,
  where they are, how exposed) as tight plain-language bullets. No preamble, no fluff.
- most_revealing = the few data points that give away the most (the "fix these first").
- This is DEFENSIVE self-audit. Frame as "here's what's inferable about you", never as
  instructions to target anyone."""


def _digest(signals: list, label: str) -> str:
    """Build a compact, rich text digest of the footprint from persisted signals."""
    accounts: list[str] = []
    attrs: list[str] = []
    breaches = 0
    stealers = 0
    hosts: list[str] = []
    mentions: list[str] = []
    brokers: list[str] = []

    for sig in signals:
        raw = sig.raw or {}
        kind = sig.kind
        if kind == "account":
            bits = [raw.get("domain") or sig.locator]
            if raw.get("display_name"):
                bits.append(f"name={raw['display_name']!r}")
            if raw.get("description"):
                bits.append(f"bio={str(raw['description'])[:160]!r}")
            if raw.get("followers") is not None:
                bits.append(f"followers={raw['followers']}")
            if raw.get("languages"):
                bits.append(f"langs={raw['languages']}")
            if raw.get("topics"):
                bits.append(f"topics={raw['topics']}")
            for r in (raw.get("top_repos") or [])[:6]:
                bits.append(f"repo={r.get('name')}({r.get('language')}):{r.get('description')!r}")
            for p in (raw.get("recent_posts") or [])[:6]:
                bits.append(f"post={str(p)[:160]!r}")
            accounts.append("  - " + " · ".join(str(b) for b in bits if b))
        elif kind == "identity_attribute":
            attrs.append(f"  - {raw.get('attribute')}={str(raw.get('value'))[:120]!r} "
                         f"(via {raw.get('platform') or sig.source})")
        elif kind == "breach":
            breaches += 1
        elif kind == "stealer_log":
            stealers += 1
        elif kind == "host_profile":
            hosts.append(f"  - {raw.get('location')} · {raw.get('isp') or raw.get('org') or ''}".rstrip(" ·"))
        elif kind == "web_mention":
            mentions.append(f"  - {raw.get('domain') or raw.get('url')}: {str(raw.get('title') or '')[:120]!r}")
        elif kind == "broker_listing":
            brokers.append(f"  - {raw.get('broker') or raw.get('domain')}")

    parts = [f"Subject: {label}"]
    if accounts:
        parts.append(f"\nRegistered platforms / profiles ({len(accounts)}):\n" + "\n".join(accounts[:60]))
    if attrs:
        parts.append("\nIdentity attributes discovered:\n" + "\n".join(attrs[:60]))
    if hosts:
        parts.append("\nIP / location:\n" + "\n".join(hosts[:10]))
    if mentions:
        parts.append(f"\nWeb mentions ({len(mentions)}):\n" + "\n".join(mentions[:30]))
    if brokers:
        parts.append("\nData-broker listings:\n" + "\n".join(brokers[:30]))
    if breaches or stealers:
        parts.append(f"\nSecurity exposure: {breaches} breach record(s), {stealers} infostealer log(s).")
    return "\n".join(parts)


def evaluate_map(signals: list, label: str = "this person") -> MapEvaluation:
    """One Opus pass over the whole footprint → structured inference + profile."""
    cfg = get_settings()
    digest = _digest(signals, label)
    resp = client().messages.parse(
        model=cfg.judge_model,
        max_tokens=4000,
        thinking={"type": "adaptive"},
        system=_cached(EVALUATE_SYSTEM),
        messages=[{
            "role": "user",
            "content": "Infer as much as you reasonably can about this person from their "
                       "assembled public footprint below, then split it into derived facts "
                       "(some as map nodes) and a profile.\n\n" + digest,
        }],
        output_format=MapEvaluation,
    )
    return resp.parsed_output
