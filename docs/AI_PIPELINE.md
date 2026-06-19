# Aresis — AI Pipeline, Triage & Cost Model

How raw evidence becomes a prioritized set of severity-rated findings with fixes,
while keeping LLM cost bounded and recall high. This is the core intelligence
design; read it with `FINDINGS_TAXONOMY.md` (the rubric) and `ARCHITECTURE.md`
(the surrounding pipeline).

## Design principles

1. **Filtering decides *depth of analysis*, never whether an item is seen.**
   Code may *promote* an item to a deeper tier; it may **never** finalize an item
   as low and drop it. Every item is read by at least one model. This is the one
   rule that keeps a cheap pre-filter from causing a catastrophic miss (e.g. an
   old-looking breach that is actually a live, reused password).
2. **Recall over cost.** Over-escalating a borderline item to the judge costs
   cents; missing a Critical destroys the product's credibility. Thresholds are
   biased toward escalation.
3. **Ask, don't guess.** When severity genuinely depends on context the data
   can't carry (was the password rotated? is the device still in use?), the
   system *asks the user* instead of bluffing a verdict.
4. **Spend the expensive model only where it adds value.** Haiku triages; Opus
   judges the items that matter and writes only the non-obvious fixes; obvious
   fixes are shown for free.
5. **Severity classification needs no examples or vector DB.** Opus knows the
   rubric from training. We inject the compact taxonomy block (`FINDINGS_TAXONOMY.md`)
   into the cached system prompt only for *consistency and testability*, not to
   teach severity.

## The funnel

```
COLLECTION  ← the cost center; the paywall gates this (input breadth + run count)
   │
   ▼
Tier 0  Deterministic route + hard-escalate           (code, free)   — never drops
   ▼
Tier 1  Haiku triage, 100% of items                   (cheap, batched) — the recall net
   ▼
Tier 2  Opus judge on the escalated set               (expensive, few) — unbounded by count
   ▼
        Long-tail rollup (reuse Haiku labels)         (pure presentation — no model call)
   ▼
        Remediation: easy=inline/free · involved=Opus on-demand · depends=after answers
```

### Tier 0 — deterministic pre-score (code, free)

Scores each evidence item from its structured `raw` fields — data sensitivity
(password ≫ address > phone > email-only), recency, source type — and applies
**hard escalation rules** (infostealer → always deep; plaintext/recent password
→ always deep). Output is a routing band + display ordering.

**It never discards.** It only decides which tier reads an item next. It is
fully deterministic, testable, and explainable — a reviewer can read the scoring
logic rather than trust "the AI decided."

### Tier 1 — Haiku triage, 100% of items (cheap, batched)

Every item — including everything Tier 0 banded low — is classified by Haiku in
batches: provisional category + severity via structured output. Haiku is the
**recall safety net**: it reads context the rules can't score and can *promote*
an item the rules under-rated into the Opus set. Bias: escalate on any doubt.

This is the only Haiku pass. The long-tail rollup later reuses these labels — it
is **not** a second Haiku call.

### Tier 2 — Opus judge, the escalated set (expensive, few, unbounded by count)

Only items that survived triage as potentially serious reach Opus. **Never capped
by count** — 10 Criticals means 10 are judged and shown; the cost is bounded
because triage correctly finds that *most* items are genuinely low, so the head
is naturally small. Per item, Opus emits:

- **Action bucket:** `fix_now` (critical) · `worth_fixing` (likely) · `depends`
  (contingent) · `no_action` (info/low).
- **For `fix_now` / `worth_fixing` — fix difficulty:** `easy` | `involved`.
  - `easy` → Opus emits the short fix **inline, in this same call**. Recognizing
    an item as an easy fix *is* knowing the fix ("leaked password → change it +
    enable 2FA"); making Opus re-read it later just to re-derive that is pure
    waste, and showing a Critical with no fix is user-hostile. Costs a few tokens;
    never a second pass.
  - `involved` → Opus **labels only**; the tailored solution/artifact is generated
    on demand (see Remediation). Saves cost and time when the user doesn't want it.
- **For `depends`** → Opus writes the minimal deciding question(s) + branch logic
  (below) and **no solution at all** — the fix can't be chosen until the answers
  are in.

## Contingency questions — "ask, don't guess"

When a verdict hinges on context the data lacks, Opus surfaces the
risk-determining factor(s) as **structured questions** (checkboxes / short text),
under strict gates:

- **Only when the answer changes the outcome.** Critical-either-way or
  fine-either-way → no question. Critical-vs-normal hinges on it → ask.
- **As few questions as possible, maximizing the severity-certainty gained per
  question.** One decisive question beats three weak ones. Question fatigue kills
  the UX, so the gate is strict.
- **Branch logic is precomputed in the same Opus judge call** ("if rotated →
  resolve to low, no action; if not → high, here is the fix"). So when the user
  ticks a box, resolution is **free** — no second judge call.
- After answers, solutions are generated **only for items that still need action**
  — never hand someone a fix for something they just reported is already fine.

This turns the model's uncertainty into a feature (it asks rather than bluffs) and
doubles as a recall mechanism: the triage layer needn't be psychic about context
it can't see.

**Category note — infostealer.** A stealer-log hit on the owner's verified
credential is never below **high** (the harvested credential must be rotated).
Critical vs high hinges on *whose machine* was infected, not whether the email is
theirs — a stealer log is tied to a machine, and the owner's email appears because
that machine held their saved login. So the contingency question is "Is <machine>
one of your devices?" — yes → critical (reimage + rotate everything + revoke
sessions, since stolen cookies bypass 2FA); no → high (rotate the leaked credential
+ revoke its sessions, no reimage). Drop below high only when the source looks like
a mislabeled combolist rather than a genuine infection.

## Remediation

| Kind | Who | When | Cost |
|---|---|---|---|
| **Easy fix** | Opus (inline at judge time) or template | shown immediately | ~free |
| **Involved fix / artifact** (GDPR & opt-out letters, infostealer playbook) | Opus | on demand (user triggers per finding) | paid perk |
| **Contingent** | — | only after questions resolve, and only if still needed | bounded |

Solutions are **on demand**: the expensive tailored write happens when the user
opens/solves a finding — including low-severity ones if the user judges them
relevant to their context. Opus runs only where the user actually cares.

## Display

Grouped, severity-sorted, nothing buried by a count cap:

1. **Fix now** / **Worth fixing** — easy fixes shown inline; involved fixes shown
   as a "generate fix" affordance (paywall point).
2. **Depends** — each with its one or two decisive questions.
3. **Low / no-action tail** — rolled up from the Haiku labels, collapsed and
   expandable. (*"In 257 breaches; 6 notable above, 251 old/low-value — general
   guidance: rotate reused passwords, adopt a manager, enable breach alerts."*)

## Cost model & paywall

**The cost center is the scan, not the solutions.** Connector quotas/credits
(HIBP domain cost, Shodan credits), single-IP rate-limit/block risk, and per-run
tokens all scale with users. Solutions are comparatively cheap and many are
templated. So the paywall gates the **scarce resource**:

- **Free:** limited input fields (e.g. one — email only), **one run**, full
  findings + easy fixes.
- **Paid (lifetime and/or tiered):** all input fields, repeat scans, and the
  tailored solutions + artifacts + contingency flow.

**Lifetime caveat:** a scan has a real per-run cost, so "lifetime + unlimited
scans" is unbounded liability — a lifetime plan must still cap scan frequency
(e.g. N re-scans/year). This is Phase 2 (auth/billing/multi-tenant); the engine
already carries the seams (`ARCHITECTURE.md §4`: nullable `user_id`, config-gated
connectors), so the shift stays additive.

## Model assignment

| Stage | Model | Why |
|---|---|---|
| Tier 0 pre-score + hard rules | none (code) | free, deterministic, testable, reviewer-legible |
| Tier 1 triage (100%) | **Haiku** | cheap, batched, good enough for "old → Low"; recall net |
| Tier 2 judge (escalated) | **Opus** | severity nuance, bucket, easy-fix inline, contingency questions |
| Involved remediation | **Opus** | tailoring + artifact quality; on demand only |
| Easy remediation | inline / template | the label *is* the fix |

Sonnet is the fallback if trap-set tests show Haiku triage recall is too low —
prefer lowering the escalation threshold or Haiku→Sonnet over adding providers.
A multi-provider ensemble (model diversity for recall) is a noted Phase-2 lever
only, not a Phase-1 dependency — provider sprawl works against maintainability.

## Recall testing (hard rule)

Maintain a **trap set**: labeled evidence items whose surface metadata
*under-sells* the true severity (an old breach that's a live reused password; a
quiet port that's exposed RDP; a "minor" device breach on critical infra). The
metric is single: **did triage escalate it?** **Do not ship if trap-set recall
regresses.** Red-teaming our own triage for false negatives is both a correctness
guarantee and a credibility signal.

## Open / TBD (settle when we build)

- Exact bucket names, thresholds, and the Tier-0 scoring weights.
- Haiku batch sizes and concurrency.
- Whether easy-fix text is Opus-inline vs a small template map (both are cheap;
  decide on consistency vs flexibility).
- Question schema (checkbox vs short-text mix) and the max-questions cap.
