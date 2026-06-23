# Connector Expansion Plan — maximize coverage with individually-obtainable sources

**Goal:** absolute coverage maximization, constrained by the one thing that keeps biting us —
**can a solo individual actually get the key?** Many OSINT sources are B2B / apply-only /
US-entity-walled and are effectively unobtainable without a company. Those are explicitly
parked. Everything in Tiers 1–2 is **self-serve for one person** (instant token or normal
paid signup, no business verification).

Already wired (baseline): HIBP, Hudson Rock, Holehe, Maigret, Shodan, GitHub, Gravatar,
GHunt, Brave, Reddit, name/CA-registry. See TOOLS.md + EXTENDED_SEARCH_SCOPE.md.

## User-base lens (what to prioritize)
- **Main base = self-auditing individuals** → their inputs are mostly **email + username**
  (everyone has them), sometimes name/photo. **Maximize email+username depth first.**
- **Technical subgroup** → has a home/server **IP**; infra exposure matters. Second priority.
- **US users** → **name/broker** removal is high-value but the data side is entity-walled;
  stay on the free registry + referral, not a paid investigative key.
- **High-risk individuals** (journalists/abuse survivors) → **photo/face** + historical
  mentions. Niche but high-impact; admin-gated.

---

## TIER 1 — add now: free or trivial, zero acquisition friction
No paid signup, no approval. Pure value-per-effort wins.

| Connector | Consumes | Adds (taxonomy #) | Acquisition | Notes |
|---|---|---|---|---|
| **EXIF/GPS parser** | photo | embedded GPS/camera/timestamp (#9) | **none** (local lib) | A user's own uploaded photo can leak home coordinates. Pure local parse, no network, no key. Highest value-per-effort. |
| **Wayback / CommonCrawl** | email, username, name | historical web mentions, deleted-but-archived pages (#8) | **none** (open API) | Catches exposure that's gone from the live web but archived. Complements Brave (live). |
| **Sherlock** | username | username presence cross-check (#4,#8) | **none** (self-hosted) | Backup/cross-validation for Maigret; cheap recall boost. |
| **GreyNoise Community** | ip | internet-background-noise / scanner reputation (#6) | **free key, instant self-serve** | Context on an IP; free community tier is self-serve. |
| **IPinfo** | ip | geo / ASN / hosting vs residential (#6) | **free token, instant** | Already named as best-pick for IP geo; trivial token. Also powers the residential check for the future IP ownership gate. |

**You need to get:** GreyNoise community key, IPinfo token. Both are instant email signups.

---

## TIER 2 — add for launch: paid but individually self-serve (no business needed)
Normal consumer signup + a card. These are where the real depth is.

| Connector | Consumes | Adds (#) | Acquisition | Why it matters |
|---|---|---|---|---|
| **Dehashed** | email, username | **actual leaked passwords/hashes** (#1) | self-serve, ~$5/mo or PAYG API | The single biggest depth jump over HIBP (HIBP says *which* breach; Dehashed shows the *credential*). Top priority paid add. |
| **IntelX (Intelligence X)** | email, username, name | leaked docs/pastes/darkweb mentions (#1,#8) | self-serve, free tier + paid API | Broadens beyond credential dumps to documents/pastes. Free tier lets us wire it before paying. |
| **LeakCheck** *(or Snusbase)* | email, username | credential leaks (alt corpus) (#1) | self-serve paid | Different leak corpus than Dehashed → recall gain. Add one, not both, unless overlap is low. |
| **Censys** | ip | host/service exposure cross-check (#6) | free tier, self-serve account | Second opinion on Shodan; catches what Shodan misses. |
| **AbuseIPDB** | ip | abuse/blocklist reputation (#6) | free tier, self-serve | Tells a user if their IP is flagged/blacklisted. |

**You need to get (priority order):** 1) **Dehashed** API (highest impact), 2) **IntelX**
key (start on free tier), 3) **Censys** free account, 4) **AbuseIPDB** free key,
5) optionally **LeakCheck/Snusbase** for a second leak corpus.

---

## TIER 3 — admin-only / sensitive: gate behind the audit-logged admin path
Powerful but ToS- or privacy-sensitive; keep `admin_only=True` (self-audit hard rule).

| Connector | Consumes | Adds (#) | Acquisition | Gate reason |
|---|---|---|---|---|
| **FaceCheck.ID** | photo | face appears elsewhere online (#9) | self-serve API, ~$0.30/search | Reverse-face is the most abuse-prone capability → admin-only, audit-logged (already designed in EXTENDED_SEARCH_SCOPE.md). |
| **TinEye** | photo | image **reuse** (where a pic was copied) (#9) | self-serve paid API | Less sensitive than face-match (it's the *image*, not the *person*), but still admin-tiered. |
| **Apify actors** | username, name | social-profile scraping (IG/TikTok/etc.) (#8) | self-serve, paid per-run | Platform-ToS-sensitive scraping → admin-only. |

**You need to get (only if pursuing photo/social):** FaceCheck.ID key, TinEye key, Apify token.

---

## PARKED — not individually obtainable (don't burn time chasing keys)
- **Epieos API** — request-only, approval unlikely for an individual → stay on **GHunt**.
- **Optery / Onerep** — B2B partner/apply-only → use as a **referral link**, not a connector;
  keep the free CA-registry catalog for enumeration.
- **PeopleDataLabs / Endato / Pipl / paid people-search APIs** — US-business-entity-walled.
- **PimEyes** — no public API.
- **Censys/Shodan enterprise, Hudson Rock paid SLA** — only if/when there's revenue.

---

## Sequencing (fits the "max collection power first" directive)
1. **Tier 1 in one pass** — all free/no-key except two instant tokens. Biggest coverage/€.
2. **Dehashed** — the one paid add that most changes results; wire + validate live.
3. **IntelX + Censys + AbuseIPDB** — breadth across leaks and IP.
4. **Tier 3** only when photo/social becomes a focus; keep admin-gated.

## Acquisition checklist for the user (copy/paste)
- [ ] IPinfo token (free, instant) — ipinfo.io
- [ ] GreyNoise Community API key (free, instant) — greynoise.io
- [ ] Dehashed API credentials (paid, self-serve) — dehashed.com  ← **highest impact**
- [ ] IntelX API key (free tier to start) — intelx.io
- [ ] Censys account + API ID/secret (free tier) — censys.io
- [ ] AbuseIPDB API key (free tier) — abuseipdb.com
- [ ] *(optional)* LeakCheck or Snusbase (paid) — second leak corpus
- [ ] *(photo/social, later)* FaceCheck.ID, TinEye, Apify

---

## Extended search v2 — research (2026-06-23)

Goal: deepen the **graph/map** beyond GitHub. Constraint unchanged — obtainable by a
solo student, free / cheap / PAYG / useful-lifetime, **no expensive monthly subs**.
Prices ~2026, verify live before buying. (Sources below are from current knowledge;
do a live pricing/ToS check next session before wiring the paid/gray ones.)

### Tier A — get these (free/PAYG, self-serve, high value)
| Tool | Brings | Access / price | Notes |
|---|---|---|---|
| **Tavily** | AI web search for a **name**, results pre-cleaned for an LLM — feeds the map "Evaluate" path far better than Brave's raw SERP. | free 1,000 credits/mo, then PAYG | The pick for name→web. Self-serve key. |
| **Bluesky (AT Protocol)** | username → public profile + posts + bio (real content, not just presence). | **free, open API** | No key. Resolve handle → feed. Clean win. |
| **Mastodon** | username → public profile/posts across instances. | free, open | Optional, lower reach than Bluesky. |
| **Apify** | **One integration, many platforms**: LinkedIn, Instagram, TikTok, X/Twitter, Google Maps reviews — via per-platform "actors". | PAYG per run, ~$5 free credits/mo | Already have `apify_token` config slot. **admin-only** (ToS-gray scraping). The single best way to reach the walled platforms cheaply. |

### Tier B — already have / free paths
- **GHunt** (have) — the only realistic path to a **person's Google Maps reviews**
  (the home-city / food / repeat-customer deductions depend on this). Fragile; free.
- **Gravatar / GitHub / Reddit** (have) — profile + content where the user is present.

### Parked — not viable for a solo student
- **LinkedIn official API** — partner-only, no profile access. Proxycurl (the popular
  LinkedIn data API) hit LinkedIn legal action and is unreliable/defunct — don't build
  on it. LinkedIn only reachable via an **Apify actor** (Tier A, admin-only, gray).
- **X/Twitter API** — paid (~$100/mo basic). Too expensive; use an Apify actor instead.
- **Instagram/Facebook/TikTok official** — no profile API; Apify actors only.
- **People Data Labs / Endato / Pipl** — US-business-entity-walled (parked already).

### Recommended sequence (when we build extended-search v2)
1. **Tavily** (name web search) — powers the map Evaluate verdict + deductions.
2. **Bluesky** (free) — real post/bio content for usernames.
3. **Apify** (admin-only) — backbone for LinkedIn / IG / TikTok / X / Google reviews;
   wire 1–2 actors first (LinkedIn + Google Maps reviews are highest value).
4. Keep **GHunt** for Google reviews until/unless an Apify Google-reviews actor proves
   it can pull a *person's* contributions (not just a place's).

### Keys to get (next session, all self-serve)
- [ ] **Tavily** API key (free tier) — tavily.com
- [ ] **Apify** token (free $5/mo credits) — apify.com  ← unlocks the walled platforms
- [ ] Bluesky needs no key (open API).
