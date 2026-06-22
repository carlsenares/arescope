# Arescope — OSINT Source Connectors

Each source is a **connector**: declares the input types it consumes, runs its query, and
emits normalized `Signal`s. Connectors are config-gated (API key / enabled flag) and must
degrade gracefully — a missing key or a rate-limit logs a coverage gap, never a scan failure.

## v1 stack

| Source | Consumes | Surfaces (→ taxonomy #) | Access | Notes / legal |
|---|---|---|---|---|
| **HIBP** | email | breach membership + data classes (#1, #3) | Paid API key (~cheap monthly) | Clean, well-documented API. The baseline. |
| **Dehashed** | email, username | leaked credentials incl. passwords/hashes (#1) | Paid subscription | Higher-fidelity than HIBP for actual creds. Consent-sensitive — self-audit only. |
| **Hudson Rock (Cavalier)** | email, username | infostealer-log exposure (#2) | Free tier API | Highest-signal "critical". Add early. |
| **Holehe / user-scanner** | email | which sites the email is registered on (#4) | Free, self-hosted (Python) | Uses password-reset enumeration; does not alert the target. |
| **Maigret** | username | account enumeration + profile extraction across 100s of sites (#4, #8) | Free, self-hosted (Python) | Richer successor to Sherlock. |
| **Sherlock** | username | username presence across sites (#8) | Free, self-hosted | Backup/cross-check for Maigret. |
| **GHunt** | email (Google) | Google account metadata (#5) | Free, self-hosted; needs Google session cookies | Maintenance-sensitive (Google changes break it). |
| **Epieos** | email | linked accounts + Google data (#5) | Free + paid API | Hosted alternative/complement to GHunt. |
| **Shodan** | ip | exposed services/ports + CVEs (#6) | Membership/API | Core for the infrastructure category. |
| **Censys** | ip | host/service exposure (#6) | API (free tier) | Complement to Shodan. |
| **AbuseIPDB / IPinfo / GreyNoise** | ip | geo + reputation enrichment (#6) | Generous free tiers | Context, not findings on their own. |

## Test build vs launch — free now / paid upgrade / best pick

What the **current test build** actually runs (free or near-free, no real spend) versus the
**paid upgrade for launch** and the **recommended best tool** per category. Prices are
approximate (≈2025/early-2026) — verify on each provider's page; several B2B ones are
quote-based. The LLM spend (Opus/Haiku) is separate — see `DISTRIBUTION.md`.

| Input → category | Free tool (test build now) | Paid upgrade (launch) | Best pick |
|---|---|---|---|
| **email** → breach membership (#1,#3) | HIBP (key needed, but cheap: ~$3.95/mo "Pwned 1") | HIBP **+ Dehashed** (actual leaked passwords/hashes, ~$5/mo or PAYG) | HIBP baseline + Dehashed for credential depth |
| **email** → infostealer (#2) | **Hudson Rock Cavalier** — free, no key | Hudson Rock paid tier (volume/SLA) | Hudson Rock (highest-signal "critical") |
| **email** → account footprint (#4) | **Holehe** — free, self-hosted (~120 sites) | Epieos (hosted, deeper Google/linked accounts, free+paid) | Holehe + Epieos |
| **email** → account metadata (#5) | GHunt — free, self-hosted (fragile; needs Google cookies) | Epieos (stable hosted) | Epieos |
| **username** → site enumeration (#4,#8) | **Maigret** — free, self-hosted (~3000 sites) | — (Maigret stays the workhorse) | Maigret |
| **username** → infostealer (#2) | **Hudson Rock** — free | Hudson Rock paid tier | Hudson Rock |
| **ip** → services + CVEs (#6) | **Shodan** — free-tier API key (limited credits) | Shodan paid + Censys | Shodan (+ Censys cross-check) |
| **ip** → geo / reputation (#6) | IPinfo / Shodan host_profile — free tiers | IPinfo paid tier | IPinfo |
| **name** → data-broker listings (#7) | **local mock shim** (~30-line endpoint matching the adapter contract) or People Data Labs free tier (~100/mo, enrichment-shaped) | **Optery / Onerep** (removal-oriented, normal tier); **Endato / Pipl** (dossier, extended/admin tier) | Optery (normal + removal) + Endato (extended) — see `DEEP_SEARCH_PLAN.md` |
| **photo** → face exposure (#9) | none (deferred) | PimEyes / FaceCheck.ID (paid, consent-gated) | deferred (Tier C) |

Notes:
- **Test build is genuinely runnable for free** on Hudson Rock + Holehe + Maigret + a Shodan
  free key; HIBP needs its cheap key for breach coverage, and **name** needs the mock shim
  (or a provider key) — without one it's an honest coverage gap, by design.
- **Name is the only category with no free real source** (broker data is paid or scraped);
  the self-audit-aligned launch pick is a *removal* provider (Optery/Onerep), not an
  investigative one. Full rationale + pricing in `DEEP_SEARCH_PLAN.md`.

## Backbone option — SpiderFoot

**SpiderFoot already is an aggregator** (200+ modules incl. HIBP/Shodan/breach/username,
with an API). Strongly consider running it as the **collection engine** for v1 and putting
the Arescope judge + remediation layer on top, instead of hand-integrating every source. It
gets to a working pipeline far faster; replace individual modules with bespoke connectors
later where precision matters. Decision to make at build time: SpiderFoot-backed vs
hand-rolled connectors (or hybrid).

## Dropped / deferred

| Source | Why |
|---|---|
| **Hunter.io** | B2B email-finder for company domains — not self-audit. Drop. |
| **Maltego** | Desktop GUI + interactive transforms — not a headless automation backbone. Drop for v1. |
| **Pimeyes** | No official API; ToS prohibits automation/scraping. Face search (#9) **deferred**; integrate manually or via FaceCheck.ID in a later phase, with consent gating. |
| **Apollo(.io)** | Sales/enrichment tool, namespace collision, off-purpose. |

## Connector contract (interface sketch)

```python
class Connector(Protocol):
    name: str
    consumes: set[InputType]          # {EMAIL, USERNAME, IP, NAME, PHOTO}
    requires_config: list[str]        # e.g. ["HIBP_API_KEY"]

    def available(self, cfg) -> bool:                 # key present + enabled
    def run(self, identifier, cfg) -> Iterable[Signal]  # may raise → logged as coverage gap
```

`Signal` is the normalized pre-judgement unit: `(source, kind, locator, raw, collected_at)`.
The normalizer dedups Signals across connectors before the judge sees them.

## Operational notes

- **Rate-limiting / IP blocks:** running many username/email checks from one server IP gets
  that IP flagged. Build connectors to tolerate 429/blocks (backoff + mark gap); add outbound
  proxy support when it starts to bite.
- **Secrets:** all source keys via env/`.env` (gitignored), like the other ares projects.
- **Self-hosted tool versions:** pin Maigret/Sherlock/Holehe/GHunt versions; they break often.
