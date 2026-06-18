# Aresis — Architecture

## 1. Pipeline overview

```
            optional inputs                         per-source raw output
  ┌──────────────────────────────┐         ┌───────────────────────────────┐
  │ name · username(s) · email(s)│         │ HIBP · Dehashed · Holehe ·     │
  │ · photo · IP                 │         │ Maigret · Shodan · Hudson Rock │
  └──────────────┬───────────────┘         │ · GHunt/Epieos · (SpiderFoot)  │
                 │                          └───────────────┬───────────────┘
                 ▼                                          │
        ┌─────────────────┐   fan-out (Celery)    ┌─────────▼─────────┐
        │ Ownership gate  │──────────────────────▶│ Source connectors │
        │ (no-op in P0)   │                       │ (pluggable)       │
        └─────────────────┘                       └─────────┬─────────┘
                                                            │ normalize → Signal[]
                                                            ▼
                                              ┌──────────────────────────┐
                                              │ Normalizer / dedup        │
                                              │ → unified Evidence set    │
                                              └─────────────┬────────────┘
                                                            ▼
                                              ┌──────────────────────────┐
                                              │ LLM Judge (structured)    │
                                              │ Signal → Finding+severity │
                                              └─────────────┬────────────┘
                                                            ▼
                                       ┌────────────────────────────────────┐
                                       │ Remediation engine                 │
                                       │ critical/high → fix plan + artifacts│
                                       │ (permission-gated execution = P2)   │
                                       └─────────────┬──────────────────────┘
                                                     ▼
                                         Report (JSON + human-readable)
```

The scan is **async**: the API enqueues a scan job, connectors run in parallel as Celery
tasks, results stream into a unified evidence set, then the judge + remediation run. The
client polls or subscribes for the report. This mirrors InsureAI's api + celery_worker split.

## 2. Components

| Component | Responsibility |
|---|---|
| **API (FastAPI)** | Accept scan requests, return scan status + report. Thin. |
| **Ownership gate** | Verify the operator owns the inputs. No-op in P0; pluggable verifier in P1. |
| **Source connectors** | One adapter per OSINT source. Each declares which input types it consumes, runs the query, and emits normalized `Signal`s. Tolerates rate-limits/blocks and degrades gracefully (a dead source ≠ a failed scan). |
| **Orchestrator** | Routes each input to the connectors that consume it; fans out via Celery; collects Signals. |
| **Normalizer/dedup** | Merge Signals across sources keyed by (subject, kind, locator) into a deduped Evidence set. Plain code, not an LLM. |
| **LLM Judge** | For each Evidence item, classify into the taxonomy + assign severity + rationale, via structured output. Tiered models (see §5). |
| **Remediation engine** | For high/critical findings, produce a fix plan (steps + deep links) and, where applicable, generated artifacts (opt-out emails, GDPR requests). Execution of those (e.g. submitting broker opt-outs) is permission-gated and lands in P2. |
| **Report builder** | Assemble findings into a severity-sorted report (machine JSON + rendered Markdown/HTML). |
| **Storage** | Postgres for scans/subjects/findings; Redis as Celery broker + transient cache. |

## 3. Data model (portability-first)

Designed so the private→service shift is additive, never a rewrite.

```
user            (id, ...)              -- NULLABLE FK everywhere in P0; the only thing P1 adds
subject         (id, user_id?, label)  -- the person/identity being scanned (you, in P0)
identifier      (id, subject_id, type ∈ {name,username,email,photo,ip}, value, ownership_verified bool)
scan            (id, subject_id, status, started_at, finished_at, config_snapshot)
signal          (id, scan_id, source, kind, locator, raw jsonb, collected_at)   -- pre-judgement
finding         (id, scan_id, signal_ids[], category, severity, title, rationale, confidence)
remediation     (id, finding_id, tier, summary, steps jsonb, artifact?, status)  -- status for P2 execution
```

**Why this shape keeps the shift cheap:**
- `user_id` is nullable from day one — Phase 1 just starts populating it + enforcing it.
- Subject identity is a row, never a global/singleton — multi-tenant is "filter by user_id".
- `ownership_verified` exists from day one — the gate flips from "always true" to "must be true".
- `config_snapshot` records which sources/keys ran, so results are reproducible as the tool grows.

## 4. Portability principles (design rules)

1. **Stateless engine.** The scan engine takes a subject + config and returns findings. No
   single-user assumptions anywhere below the API layer.
2. **Ownership gate is a pluggable strategy.** `AssertOwnership` (P0) → `VerifyOwnership`
   (P1: email magic-link / DNS-style proof / username bio token). Same interface.
3. **Config-driven sources.** Each connector is enabled/disabled and keyed via config, so
   P0 runs on free tiers and paid sources are added without code changes.
4. **PII is sensitive from day one.** Findings encrypt notable PII at rest; every scan has a
   retention TTL (default e.g. 30d) with a pruning job. This is a legal requirement for a
   service and free to adopt now.
5. **Graceful degradation.** A blocked/ratelimited/absent source logs a gap in the report
   ("Shodan skipped: no API key") rather than failing the scan — and the report never
   implies coverage it didn't have.

## 5. LLM usage

- **Judge** (Signal → Finding+severity): `claude-opus-4-8` for severity/rationale, with
  **structured outputs** (`output_config.format` + a JSON schema for the Finding) so the
  result is validated, not parsed. Adaptive thinking on. For high-volume/cheap normalization
  passes, drop to `claude-sonnet-4-6` or `claude-haiku-4-5`.
- **Remediation** (Finding → fix plan/artifact): `claude-opus-4-8` — this is where reasoning
  quality matters most (tailoring fixes to the user's context).
- **Cost** (per §3 of the project memory): ~€0.25–0.45 per full run on Opus, ~€1 heavy.
  Tier the models to roughly halve it. Prompt-cache the static taxonomy/system prompt; the
  variable findings aren't cacheable.
- **Tiering rule of thumb:** Haiku for dedup/normalization hints, Sonnet for routine
  severity calls, Opus for critical-finding judgement + all remediation.

## 6. Deployment

Containerized like InsureAI: `api`, `celery_worker`, `redis`, `postgres`, plus the OSINT
tools either vendored into the worker image (Maigret/Sherlock/Holehe/GHunt are pip/CLI) or
run as a sidecar (SpiderFoot). Sits behind the shared InsureAI nginx as another vhost
(e.g. `aresis.<domain>`) on the consolidated server. Watch disk: cap scan/screenshot
retention; add outbound proxy support when single-IP rate-limiting starts to bite.
