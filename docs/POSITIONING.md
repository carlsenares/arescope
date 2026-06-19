# Aresis — Positioning (what it is, and how it differs from what exists)

Honest version. This is a **crowded space**: the components all exist, and some
combinations of them exist commercially. Aresis's edge is a *specific combination*
+ an ethical posture, not a first-of-its-kind primitive. The near-term goal is a
standout **portfolio** build (architecture + applied AI + security judgement), not
to out-scale incumbents.

## The system

One **verified email** is the anchor; everything fans out from it and is assembled
into an identity graph, then judged and remediated:

| Source (`TOOLS.md`) | Surfaces | Taxonomy |
|---|---|---|
| HIBP | breach membership + data classes | #1, #3 |
| Hudson Rock | **infostealer logs** (live stolen creds/sessions) | #2 |
| Holehe | which sites the email is registered on (footprint) | #4 |
| Epieos / GHunt | Google/account metadata, linked services | #5 |
| Dehashed | actual leaked passwords (higher fidelity) | #1 |
| Maigret | username footprint across sites (**only on a derived/owned handle**) | #4, #8 |
| Shodan | exposed services/ports/CVEs (IP seed) | #6 |
| Data-broker (#7) | people-search listings → **opt-out** | #7 |

Pipeline: collect → normalise/dedup → **cluster (Tier 0)** → **Haiku triage (Tier
1)** → **Opus judge (Tier 2)**: severity + rationale + contingency questions →
**remediation**: T0 guidance + T1 generated artifacts (opt-out / GDPR/CCPA) →
report + (planned) **identity graph** visualisation.

## The landscape

- **Breach checkers** — HIBP, Mozilla Monitor. Email → breach list. No infostealer
  depth, no footprint, no synthesis, no remediation.
- **OSINT aggregators** — FootprintIQ, InfoHunter, Brightside AI. The closest.
  FootprintIQ already does username/email/phone → severity scoring + step-by-step
  removal guides incl. **pre-filled GDPR/CCPA** requests. But: **no ownership
  gate** — you can search anyone ("authorised investigations"), i.e. dual-use.
- **Data-broker removal** — Incogni, DeleteMe, Optery, Onerep. Mature, automated,
  400–850 brokers. A *commodity* we will not out-cover.

## Where Aresis is genuinely differentiated

1. **Self-audit by design (the real moat).** The aggregators are dual-use and
   ungated — structurally capable of doxxing. Aresis's seeds-vs-filters gate
   (`OWNERSHIP_VERIFICATION.md`) makes it *structurally unable* to be a
   people-search tool. That ethical posture is the identity and the Epieos story.
2. **AI judgement depth, not a score.** Incumbents output a numeric exposure
   score. Aresis runs an LLM judge that gives per-finding *rationale*, asks
   *contingency questions* that actually resolve severity, and writes *tailored*
   remediation/artifacts — judgement, not a gauge.
3. **The identity graph.** Because every node is anchored to a verified identity,
   we can visualise the exposure as a colour-coded graph (severity + connections) —
   how much of you is out there and how it links. Not seen in the incumbents.

## Where we deliberately don't compete

- **Broker coverage.** We surface listings + generate the opt-out and (later) hand
  off / integrate; we don't try to beat Incogni/DeleteMe on the 400+ broker grind.
- **Investigating others.** Ever. That's the whole point.

## Honest caveat

FootprintIQ et al. mean "we aggregate + add AI" is **not** novel on its own. The
defensible story is the *ethical gate + judgement depth + graph*, and — for now —
a clean, well-architected portfolio piece. Don't chase false novelty by loosening
the gate (e.g. name-as-seed + ID); that trades the one real moat for features the
market already commoditised.
