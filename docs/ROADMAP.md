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
- **Auth + ownership verification** (the gate flips from no-op to mandatory). Per-input proof,
  fields optional & independently verified — full design in `OWNERSHIP_VERIFICATION.md`:
  email = magic-link; username = OAuth (bio-token fallback) + linked verified email;
  ip = source-match, residential/mobile only. Name never seeds a scan (filter-only).
  Detailed, explained error states (ⓘ → "why we verify" page).
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

## Phase 4 — Aresis for Business (expansion)
Audit a **non-person entity** (company / domain / brand / infrastructure), not an individual.
This is where the inputs *deferred from personal* become first-class — same engine, the gate
just swaps strategy. The portability rules (nullable `user_id`, config-gated connectors,
ownership-gate-as-strategy) already support it; this is additive, not a rewrite.
- **Ownership proof = DNS-TXT domain control** — one robust standard proof legitimately unlocks
  the domain, its IP ranges, and its corporate mailboxes.
- Sources that personal excludes become core: HIBP `breachedDomain` (which company addresses are
  breached), Hudson Rock domain infostealer, Shodan/Censys attack-surface on datacenter IPs,
  leaked-secret + typosquat/brand monitoring.
- Tailored business report (asset inventory + exposure posture over time), org-level billing.

## Non-goals
- People-search / investigating others. Self-audit only (legal + positioning).
- Fully automated login-and-change-settings remediation (T3 outside data-broker opt-outs).
- Storing user account credentials.
- **Business edition scans the org's own assets only** — employee-exposure angles stay
  consent/authorization-gated (the company's HR/legal call), never ad-hoc people-search.
