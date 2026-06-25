# Connectors — the live search-tool reference

Every source Arescope queries, what it consumes, **exactly what it brings**, its
access tier, and price. This is the *current registry* (23 connectors, see
`arescope/connectors/registry.py`) — the authoritative "what runs today" doc.
`TOOLS.md` is the original v1 design rationale; `CONNECTOR_EXPANSION_PLAN.md` is the
acquisition plan. This file is the operational truth.

**How to read it**
- **Access:** `key` (needs an API key/token), `free` (no key), `self-hosted` (a
  Python lib / CLI bundled in the image), `admin-only` (crosses the self-audit line,
  runs only for admins).
- Every connector **degrades gracefully** — a missing key, rate-limit, or block logs
  a coverage gap and never fails the scan.
- **Status** = what we actually hold right now.
- Prices are approximate (~2026) — verify on each provider's page before relying on
  them. Self-audit usage is ~1 lookup per input per scan, so free tiers go far.

---

## By input type — what each input buys you

### EMAIL → `hibp · leakcheck · hudsonrock · holehe · gravatar · ghunt`
The richest input. Covers breaches, leaked passwords, infostealer infections,
account footprint, and Google/Gravatar profile data.

| Tool | Brings (from an email) | Access | Price | Status |
|---|---|---|---|---|
| **HIBP** | Which breaches the email is in + the data classes each exposed (#1,#3). | key | ~$3.95/mo (Pwned 1) | ✅ have |
| **LeakCheck** | Per-breach leaked **fields** (password*, address, phone, DOB…) + source attribution; the credential-depth source. *(stores only a masked password preview)* | key | $70 lifetime (400/day) | ✅ have |
| **Hudson Rock** | Infostealer-log exposure — device infected, creds + cookies stolen (#2, highest-signal critical). | free | free | ✅ live |
| **Holehe** | Which ~120 sites the email is registered on, via password-reset enumeration (silent) (#4). | self-hosted | free | ✅ live |
| **Gravatar** | Public Gravatar profile + avatar tied to the email. | free | free | ✅ live |
| **GHunt** | Google account metadata: display name, profile photo (real vs default), maps/reviews, etc. (#5). | self-hosted | free (needs Google cookies) | ⚠ fragile |

### USERNAME → `leakcheck · hudsonrock · maigret · sherlock · github · reddit · urlscan`
Account correlation across the web + breach exposure keyed on the handle.

| Tool | Brings (from a username) | Access | Price | Status |
|---|---|---|---|---|
| **Maigret** | Account enumeration + profile extraction across ~3000 sites (#4,#8). The workhorse. | self-hosted | free | ✅ live |
| **Sherlock** | Account presence cross-check (~400 sites) — corroborates Maigret. | self-hosted | free | ✅ live |
| **LeakCheck** | Breaches that leaked this username + fields. | key | (above) | ✅ have |
| **Hudson Rock** | Infostealer exposure keyed on the username. | free | free | ✅ live |
| **GitHub** | Public profile: real name, company, location, bio, public email, repos. | free | free (token lifts 60→5000/hr) | ✅ live |
| **Reddit** | Public Reddit profile + activity. | free | free (optional app creds for OAuth) | ✅ live |
| **urlscan** | Pages in urlscan's scan index that mention the handle (#8). | key | free tier | ✅ have |
| **Instagram (Camoufox)** | Public IG profile via stealth browser: name, bio, follower count, profile photo, recent post captions + tagged locations (#8). Logged-in view with a stored session. | self-hosted (Camoufox) | free | ⚠ admin-only, unvalidated |

### PHONE → `leakcheck · ipqs · numverify · ignorant · phoneinfoga`
Breach exposure + reputation + which apps the number is registered on.

| Tool | Brings (from a phone) | Access | Price | Status |
|---|---|---|---|---|
| **LeakCheck** | Breaches that leaked the number + associated data (address/name). | key | (above) | ✅ have |
| **IPQS** | Fraud/spam reputation, recent-abuse, line type (VOIP vs mobile → SIM-swap risk), carrier. | key | free tier (~5k/mo) | ✅ have |
| **NumVerify** | Validation: carrier, country/geo, line type. Also map enrichment. | key | free tier (100/mo) | ✅ have |
| **Ignorant** | Which sites the number is registered on (Amazon/Instagram/Snapchat) — Holehe-for-phone. | self-hosted | free | ✅ live |
| **PhoneInfoga** | Phone footprinting (carrier/line/reputation lookups). | self-hosted | free | ⏸ dormant (needs Go binary in image) |

### IP → `shodan · ipinfo · abuseipdb · censys · virustotal`
What your address gives away + whether it's flagged. All emit one merged "your IP"
cluster.

| Tool | Brings (from an IP) | Access | Price | Status |
|---|---|---|---|---|
| **Shodan** | Exposed services/ports + CVEs + host profile (#6). | key | free key (limited) / paid | ✅ have (academic) |
| **IPinfo** | Geo, ASN/org, hosting-vs-residential, hostname. | key | free tier (50k/mo) | ✅ have |
| **AbuseIPDB** | Abuse-report / blocklist reputation. | key | free tier (1k/day) | ✅ have |
| **Censys** | Host/service exposure cross-check (Censys Platform). | key | free tier (Platform PAT) | ✅ have |
| **VirusTotal** | Malicious-engine reputation + AS owner. **NON-COMMERCIAL licence.** | key, **admin-only** | free (non-commercial) | ✅ have (admin) |

### NAME → `brokers · brave · urlscan`
The footprint everyone has, regardless of platform use.

| Tool | Brings (from a name) | Access | Price | Status |
|---|---|---|---|---|
| **Brokers (registry)** | Enumerates consumer data-broker / people-search sites + opt-out links (#7, removal track; `confirmed:false`). | free | free (bundled catalog) | ✅ live |
| **Brave** | Web "vanity search": news, records, profile/social mentions tied to the name (#5). | key, **admin-only** | $5 free credits/mo | ✅ have |
| **urlscan** | Scanned pages mentioning the name. | key | free tier | ✅ have |

### PHOTO → `exif`
| Tool | Brings (from a photo file) | Access | Price | Status |
|---|---|---|---|---|
| **EXIF/GPS** | Embedded GPS coordinates (home/work doxxing risk) + camera make/model + capture time (#9). Pure-local, no network. | self-hosted | free | ✅ live |

---

## Cost summary

- **Recurring spend = €0** today. Everything we run is free, self-hosted, a free
  tier, or a **lifetime** purchase (LeakCheck $70 one-off).
- **Held paid/keyed:** HIBP (~$3.95/mo — the only monthly), LeakCheck ($70 lifetime),
  Shodan (academic), Brave ($5 free credits/mo). All others are free tiers.
- **The real cost center is the LLM** (Opus judge in *search* mode), not connectors —
  see `DISTRIBUTION.md`. **Map mode runs no Opus**, so a map is pure connector calls.
- **Parked on cost / unobtainable:** Dehashed ($22/mo), Epieos (approval-only),
  Optery/Onerep (B2B), PeopleDataLabs/Endato/Pipl (US-entity-walled), PimEyes (no API).
  See `CONNECTOR_EXPANSION_PLAN.md`.

## Rate-limit notes (per-input, per scan ≈ 1 lookup)
- **LeakCheck** 400/day (email+username) + 30/day (keyword) — caps map results at 60.
- **IPinfo** 50k/mo · **AbuseIPDB** 1k/day · **NumVerify** 100/mo (the tightest free tier)
  · **IPQS** ~5k/mo · **Brave** $5 credits/mo · **urlscan** free tier.
- **Maigret** full pass ~4 min/username (capped to top-50 in map mode + offered as the
  fast option in search mode).
