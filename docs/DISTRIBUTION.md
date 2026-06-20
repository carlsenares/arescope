# Aresis — Distribution & Business Model

How Aresis reaches a lot of people without losing money. The space is crowded
(see `POSITIONING.md`), so the goal is **reach + break-even**, not margin
maximization. Model: **open-core, AGPL**.

## TL;DR

- **Open-source the engine + free connectors (AGPL).** Builds trust, gets the
  GitHub/portfolio credibility, and AGPL stops a SaaS competitor closing it.
- **Hosted is the paid product** — it does the parts that *can't* be self-hosted
  credibly: the enforced ownership gate (`OWNERSHIP_VERIFICATION.md`) and
  **aggregated OSINT keys**.
- **No ads, ever.** A privacy product funded by an ad network is a category
  contradiction and kills the only moat we have (trust).
- The thing that has to break even is **not per-scan cost** — it's the **fixed
  ~$300+/mo OSINT subscription floor**. Everything below is built to defend it.

## The two cost centers (they behave differently)

| Cost | Type | Who pays | Risk |
|---|---|---|---|
| Anthropic / LLM | **variable** per scan (~€0.5–1 worst case, capped by triage cascade) | BYO-key, or per-scan price | Low — always price-matchable |
| Free connectors (Holehe, Maigret, Sherlock, Hudson Rock free, HIBP ~$4) | ~fixed, trivial | absorbed | Negligible |
| **Paid OSINT tiers (Dehashed, Shodan, Epieos)** | **fixed ~$300+/mo flat** | ??? | **This is the whole problem** |

A variable cost you can always cover by pricing the scan. A **fixed floor you
pay on a zero-revenue month** — that's what sinks a side project. The rest of
this doc is about never paying that floor before revenue covers it.

## Tiers

| Tier | Sources | LLM | Ownership gate | Your floor |
|---|---|---|---|---|
| **0 — Self-host (OSS)** | free connectors + **BYO all keys** | BYO-key | removable (their box, their problem) | **$0** |
| **1 — Hosted Free/Basic** | free connectors only | BYO-key *or* per-scan credits | **enforced** | **~$4/mo** (HIBP) |
| **2 — Hosted Premium** | + paid sources (Dehashed/Shodan/Epieos) | per-scan credits or bundled | **enforced** | **the ~$300 floor — must be covered by this tier's revenue** |

Tier 1 is the "available to a lot of people" tier and costs you almost nothing.
Tier 2 is where the floor lives, and it is **structurally walled off** so only
paying premium users can trigger a paid-API call.

## Defending the $300 floor — five rules

1. **Never pay the floor before demand covers it (staged unlock).**
   Launch Tier 2 sources *off*, shown as "Premium sources — join waitlist."
   Subscribe to Dehashed/Shodan/Epieos only when **pre-committed premium MRR ≥
   that source's monthly cost.** Each paid source is its own floor; turn them on
   one at a time, cheapest-highest-signal first.

2. **Cohort the floor to the tier that causes it.** Paid-API calls are gated to
   Tier 2 subscribers only. A free/Tier-1 scan can *never* hit a metered source.
   This makes the floor a function of paying users, not total traffic.

3. **Know each source's pricing model and treat them differently.**
   - *Flat monthly tier* (must amortize across subscribers) → covered by rule 1's
     break-even count.
   - *Per-query / PAYG* (some providers offer it) → **pass through**: charge the
     user per premium lookup; your cost ≈ $0 above what they paid.
   Prefer PAYG/metered plans over flat tiers wherever a provider offers both —
   it converts a fixed floor into a variable, pass-throughable cost.

4. **Offer BYO-OSINT-key in Premium.** A power user who already has a Dehashed or
   Shodan key plugs it in and is removed from your floor entirely. Same trick as
   BYO-Anthropic-key, applied to the expensive sources.

5. **Cap and meter.** Per-user and global rate limits on paid sources so a single
   power user (or abuse) can't run the metered bill past the tier's revenue.
   Ties into the existing connector backoff/coverage-gap behavior.

## Break-even math (the number to run the business on)

```
Floor      F = fixed paid-OSINT cost/mo            (e.g. $300)
Margin     m = premium price − variable cost/user  (LLM + per-query OSINT + infra)
Break-even N = F / m   premium subscribers
```

Worked example — `F = $300`, premium `$12/mo`, variable `~$4/user` → `m = $8` →
**N ≈ 38 paying subscribers** to cover one $300 source bundle. That's the single
number to track. Each additional flat-tier source raises `F` and pushes `N` up —
which is exactly why rule 1 stages them in behind revenue.

Levers if `N` is too high to hit:
- raise price or move premium sources to PAYG pass-through (shrinks `F`),
- push more users to BYO-key (shrinks variable cost → raises `m`),
- delay turning the source on (keeps `F` at $0 until the waitlist is real).

## Anti-patterns (decided against)

- **Ads.** Privacy product + attention economy = contradiction; destroys trust,
  the only moat. Hard no.
- **Flat subscription for bursty usage on the free tier.** Self-audit is bursty
  (scan → fix → leave); flat pricing either overcharges users or eats variable
  cost. Free/Basic = BYO-key or credits; only Premium is subscription.
- **Turning on all paid sources at launch.** Pays three floors against zero
  revenue. Stage them.
- **MIT/permissive license.** Lets a funded competitor close our engine. AGPL.

## Open-source boundary

| Open (AGPL) | Closed / hosted-only |
|---|---|
| engine, connector interface, free connectors, normalizer, judge *interface* | enforced ownership gate, aggregated OSINT keys, identity-graph correlation, tuned remediation playbooks |

Open enough to earn trust and contributions; the defensible work (gate +
aggregation + correlation) stays the reason to pay for hosted.

## Open questions

- Exact monthly cost + pricing model (flat vs PAYG) of Dehashed, Shodan, Epieos
  at the tier Aresis needs — fill the real numbers into the break-even model.
- Premium price point (the `$12` above is a placeholder) — set after measuring `F`.
- Outbound proxy cost (rate-limit mitigation, see `TOOLS.md`) — a second smaller
  fixed cost to fold into `F` once username/email volume grows.
</content>
</invoke>
