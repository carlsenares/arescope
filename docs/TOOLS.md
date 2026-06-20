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
