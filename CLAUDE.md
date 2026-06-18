# CLAUDE.md — Aresis build context

**What this is:** a personal exposure scanner + privacy remediation engine. Inputs you own
(name, username(s), email(s), photo, IP) → OSINT sources → LLM judges each finding by
severity → proposes fixes for the dangerous ones. Goal = shrink the user's footprint, not
investigate others. Read `README.md` then `docs/` before writing code.

## Read order
1. `docs/ARCHITECTURE.md` — pipeline, components, data model, portability rules.
2. `docs/FINDINGS_TAXONOMY.md` — finding categories → severity → remediation (the core logic).
3. `docs/TOOLS.md` — source connectors + the SpiderFoot-vs-hand-rolled decision.
4. `docs/ROADMAP.md` — what to build in which phase.

## Hard rules
- **Self-audit only.** Never build people-search/investigation features. The ownership gate
  is a no-op in Phase 0 but the data model and flow assume it becomes mandatory (P2).
- **Design for private→service portability** (`ARCHITECTURE.md` §4): nullable `user_id`
  everywhere, stateless engine, config-gated connectors, PII encryption + retention TTL from
  day one. The shift to a service must be additive, not a rewrite.
- **Connectors degrade gracefully** — a missing key / rate-limit / block logs a coverage gap;
  it never fails the scan, and the report never implies coverage it didn't have.
- **Secrets via `.env`** (gitignored), like the other ares projects.

## Stack
Python 3.12 · FastAPI · Celery + Redis · Postgres · Anthropic SDK. Mirrors InsureAI so it
deploys behind the shared nginx on the consolidated server (vhost e.g. `aresis.<domain>`).

## LLM
- Judge (Signal→Finding+severity) and remediation: `claude-opus-4-8` with **structured
  outputs** (`output_config.format` + JSON schema) and adaptive thinking. Do not parse free
  text — constrain the output to the Finding schema.
- Tier for cost: `claude-haiku-4-5` / `claude-sonnet-4-6` for normalization/routine calls,
  `claude-opus-4-8` for critical-finding judgement + all remediation.
- Always consult the `claude-api` skill before writing Anthropic SDK code; don't guess SDK
  shapes or model IDs.

## Phase 0 → 1 first targets
Scaffold the stack + data model, then 3–4 connectors end to end (HIBP, Holehe, Maigret,
Hudson Rock) → normalize → judge → T0/T1 remediation → report. Prototype the collection layer
on SpiderFoot first to validate the pipeline cheaply before hand-rolling connectors.
