# Aresis — Roadmap

Phased so the private tool and the eventual service are the *same engine*, with the service
adding a thin gate + per-user storage on top (never a rewrite). See `ARCHITECTURE.md` §4.

## Phase 0 — Foundations (now)
- Architecture + taxonomy docs (this directory). ✅
- Repo + stack scaffold (FastAPI + Celery + Redis + Postgres + Anthropic SDK).
- Data model from `ARCHITECTURE.md` §3 (with nullable `user_id`, `ownership_verified`).
- **Decision:** SpiderFoot-backed collection vs hand-rolled connectors (or hybrid). Prototype
  SpiderFoot first to validate the pipeline cheaply.

## Phase 1 — Private MVP (single user, no auth)
- 3–4 connectors end to end: HIBP + Holehe + Maigret + Hudson Rock (covers taxonomy #1–4 +
  the critical #2). Add Shodan if you have an IP worth scanning.
- Normalizer/dedup → unified evidence set.
- LLM judge with structured output (Opus 4.8) → findings + severity + rationale.
- Remediation **T0 (guided) + T1 (generated artifacts)** for every finding category.
- Report: severity-sorted JSON + rendered Markdown. Run it on your own identifiers.
- Retention TTL + pruning job in from the start.

## Phase 1.5 — Harden the engine
- Remaining connectors (Dehashed, Censys, GHunt/Epieos, IP enrichment).
- Model tiering (Haiku/Sonnet for normalization, Opus for critical + remediation) to cut cost.
- Prompt-cache the static taxonomy/system prompt.
- Connector resilience: backoff, coverage-gap reporting, optional outbound proxy.

## Phase 2 — Turn it into a service
- **Auth + ownership verification** (the gate flips from no-op to mandatory): email magic-link
  / username-bio-token / domain proof before any scan runs.
- Multi-tenant: populate + enforce `user_id`; per-user isolation + encryption.
- Next.js frontend (matches the ares house style) for input, report, and the remediation
  checklist.
- Billing + the legal layer (ToS, consent, data-processing terms) — required before opening up.
- **Automated remediation, scoped:** data-broker opt-out submission (T2→T3, the Incogni/DeleteMe
  model). *Not* automated changes to arbitrary user accounts.

## Phase 3 — Optional extensions
- Face/photo exposure (#9) via FaceCheck.ID or manual Pimeyes, with strict consent gating.
- Scheduled re-scans + "exposure score over time" tracking.
- Alerting on new breaches/leaks for monitored identifiers.

## Non-goals
- People-search / investigating others. Self-audit only (legal + positioning).
- Fully automated login-and-change-settings remediation (T3 outside data-broker opt-outs).
- Storing user account credentials.
