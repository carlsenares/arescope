# Aresis

**Personal exposure scanner & privacy remediation engine.** Aresis takes a set of
optional identifiers you own (name, username(s), email(s), photo, IP), runs them through
a battery of OSINT sources, has an LLM judge each finding by severity (info → critical),
and proposes concrete fixes for the dangerous ones — with the goal of *shrinking your
digital footprint*, not investigating others.

## Status

Pre-implementation. Currently: architecture + design docs only. See `docs/`.

- Phase 0 (now): private, single-user tool. No auth. Run scans on identifiers you own,
  to test the engine and build the findings → severity → remediation pipeline cheaply.
- Phase 1+: optional auth + ownership verification turns it into a privacy SaaS. The
  engine is the same; only a thin gate and per-user storage are added. See `docs/ROADMAP.md`.

## Positioning (read this before building)

Aresis is a **self-audit** tool. It scans identifiers the operator owns or has consented
access to. It is **not** a people-search / investigation product — that direction is
legally fraught (ToS, doxxing, payment processors) and low-value in everyday use. The
ownership-verification gate (`docs/ARCHITECTURE.md` §Auth) is a no-op in Phase 0 (you
assert ownership) and becomes mandatory the moment other users are involved.

## Docs

- `docs/ARCHITECTURE.md` — system design, data model, portability principles.
- `docs/FINDINGS_TAXONOMY.md` — the core: finding types → severity logic → remediation.
- `docs/TOOLS.md` — OSINT source connectors, inputs/outputs, legal flags.
- `docs/ROADMAP.md` — phased plan from private MVP to service.
- `CLAUDE.md` — build context for Claude Code.

## Stack

Python 3.12 · FastAPI · Celery + Redis · Postgres · Anthropic SDK (Claude). Mirrors the
InsureAI stack so it reuses the same deploy pattern (behind the shared nginx) on the
consolidated server.
