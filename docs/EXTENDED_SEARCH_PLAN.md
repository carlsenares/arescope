# Extended Search — the build plan for the "how is this possible" map

Goal: the map fills with a **massive, real-time web** from one or two inputs. This is
the exact connector plan to get there, ordered **broad → narrow** (reach = % of users
it produces nodes for). Pricing is from a 2026 live check where noted; **verify before
buying**. Self-audit usage ≈ 1 lookup per input per scan, so free tiers stretch far.

Constraint (unchanged): solo-student obtainable — free / cheap / PAYG / useful-lifetime.
No expensive monthly lock-in. Pricey-but-exceptional items are flagged, not hidden.

## Model decision — Sonnet for Tavily, Opus only for Evaluate
Map mode runs **no per-node Opus**. The Tavily (and any web/scrape) results get turned
into graph nodes by **Claude Sonnet 4.6** — that step is extraction/normalization
("pull the person's links/facts from these results"), which is exactly the
cheap-tier job in CLAUDE.md, not deep judgement. **Opus is reserved for the on-demand
"Evaluate" verdict** over the assembled graph (GRAPH.md §13a). 
- *Only argument against Sonnet:* **person disambiguation** (is this the right "John
  Smith" in the web results?) is the one place reasoning matters. Mitigate without
  Opus: query Tavily with the most specific handle/email/location available, and have
  Sonnet attach a confidence + "why this is likely them" to each node so the Evaluate
  pass (Opus) can discount weak links. Net: **Sonnet is the right call.** (Haiku is
  viable for pure link extraction if we want it even cheaper; Sonnet for anything with
  light inference.)

---

## TIER 1 — BROAD (≈ every user): the spine of the map
These produce nodes for almost anyone with an email / username / name.

| Source | Input → brings | Reach | Access / price | Status |
|---|---|---|---|---|
| **Tavily** | name (+context) → AI web search, LLM-clean results → web-presence nodes (articles, profiles, records). Powers Evaluate. | ~all | **free 1,000 credits/mo**, then PAYG **$0.008/search** | ✅ key in .env |
| **OSINT.industries** | email / phone / username → registered accounts across **100s** of platforms *with profile data* (broader than Holehe/Maigret). One call → dozens of nodes. | ~all | subscription + non-expiring credits (entry tier; check `app.osint.industries/pricing`) | ⬜ **get — biggest single node multiplier** |
| **Email-enrichment API** (People Data Labs / Enrich.so / Datagma) | email or name → full name, employer, location, linked social profiles. | ~most | **PDL free 100/mo, then ~$0.01/record PAYG**; others similar | ⬜ get one (PDL self-serve PAYG — earlier "walled" note was wrong) |
| HIBP · LeakCheck · Hudson Rock · Holehe · Gravatar | email → breaches, leaked fields, infostealer, registrations, avatar | ~all | have | ✅ live |
| Maigret · Sherlock · GitHub · Reddit | username → accounts + profile content | ~all | have | ✅ live |
| Brave · urlscan · brokers | name → web mentions + broker listings | ~all | have | ✅ live |

**Tier-1 adds to get:** OSINT.industries (subscription, top priority — it's the single
biggest "graph explodes" addition), one email-enrichment API (PDL PAYG).

---

## TIER 2 — MID (many users): content + identity richness
Real posts/photos/profile data, not just "an account exists here".

| Source | Input → brings | Reach | Access / price | Status |
|---|---|---|---|---|
| **Bluesky (AT Protocol)** | username → profile + **actual posts/bio** | growing | **free, open API, no key** | ⬜ add (free win) |
| **GHunt** | email → Google name, profile photo (real vs default), **Maps reviews/contributions** (home-city / cuisine / repeat-customer deductions) | Google users (~most) | have (free, fragile) | ✅ keep |
| **Apify** (backbone) | username/name → **Instagram, TikTok, X/Twitter, LinkedIn, Google-Maps reviews** via per-platform actors | many | **$5 free credits/mo**, then PAYG ($0.20/CU + some per-result, e.g. Maps ~$2/1k) | ⬜ get token — **admin-only** (ToS-gray) |
| **Mastodon** | username → profile/posts | niche-growing | free, open | ⬜ optional |
| Phone stack (IPQS/NumVerify/Ignorant + LeakCheck) | phone → reputation, carrier, registrations, breaches | phone users | have | ✅ live |
| **Twilio Lookup** | phone → authoritative carrier + line-type + caller name | phone users | PAYG ~$0.01–0.05/lookup | ⬜ optional |

**Tier-2 adds to get:** Bluesky (free, do first), Apify token (admin backbone for the
walled platforms — wire LinkedIn + Google-Maps-reviews actors first).

---

## TIER 3 — NARROW (a subset / niche, but jaw-dropping when present)

| Source | Input → brings | Reach | Access / price | Status |
|---|---|---|---|---|
| Shodan · IPinfo · AbuseIPDB · Censys · VirusTotal | ip → services, geo, reputation | technical / self-hosters | have | ✅ live |
| **LinkedIn — connect-your-own-account** (Unipile / Phyllo) | the user links *their own* LinkedIn → full profile, ToS-safe for self-audit | professionals | Unipile ~per-connected-account/mo; Phyllo creator-oriented | ⬜ evaluate — **the clean LinkedIn path** (no scraping) |
| **LinkedIn — scraper actor** (Apify) | name/url → public profile | professionals | via Apify (admin-only, gray) | ⬜ fallback only |
| **FaceCheck.ID** | photo → where the **face** appears online | photo present | self-serve, ~$0.30/search | ⬜ **admin-only** (most abuse-prone) |
| **TinEye** | photo → image **reuse** | photo present | PAYG | ⬜ admin-only |
| **Strava / fitness** | username → **public activity heatmap = home/run routes** (notorious location leak) | athletes (~10–20%) | free public endpoints (gray) | ⬜ high-impact niche |
| **Venmo / Cash App / PayPal.me** | handle → public transactions / existence | payment-app users | public pages (gray) | ⬜ niche |
| **Spotify / Steam / gaming** | username → public profile/activity | gamers/music | free APIs (Spotify free, Steam free key) | ⬜ niche, cheap |
| **Domain / WHOIS / crt.sh** | domain (new input) → registrant, subdomains, certs | domain owners (~10%) | free (crt.sh, RDAP) | ⬜ niche, free |
| **Crypto address** | wallet (new input) → on-chain activity | crypto users | free explorers | ⬜ niche |
| **US public records** (Endato/People-search paid) | name → address history, relatives | US users | paid, US-entity-walled | ⛔ parked |

---

## Pricey-but-exceptional (flagged per your ask)
- **OSINT.industries** — not free, but the **single biggest map multiplier** (100s of
  account modules per email/phone/username). Worth a low subscription tier; credits
  don't expire. *Top recommendation despite cost.*
- **Apify** — cheap to start ($5/mo free) but per-result fees add up at volume; the
  *only* affordable route to LinkedIn/IG/TikTok/X/Google-reviews. Admin-only.
- **PDL enrichment** — ~$0.01/record PAYG is cheap per-call but a paid dependency.

## Parked / not viable solo
LinkedIn official API (partner-only since 2018, denies enrichment tools — **no open
successor**; use connect-your-own-account or an Apify actor instead) · X/Twitter API
(~$100/mo) · Proxycurl (LinkedIn legal action, unreliable) · Endato/Pipl
(US-entity-walled) · PimEyes (no API).

---

## Acquisition checklist (next session, by priority)
- [x] **Tavily** key — in .env (`ARESCOPE_TAVILY_API_KEY`)
- [ ] **OSINT.industries** — subscription + API key (biggest graph multiplier)
- [ ] **Apify** token — free $5/mo (admin-only backbone; wire LinkedIn + Maps-reviews actors)
- [ ] **People Data Labs** — free 100/mo then PAYG (email/name enrichment)
- [ ] Bluesky — no key (open API)
- [ ] *(later/niche)* Twilio Lookup, FaceCheck.ID (admin), Strava, Steam/Spotify, crt.sh

## Why the graph looks "impossible"
It's the **convergence + multiplicity** compounding:
1. **One input fans out** — OSINT.industries + Maigret/Sherlock + enrichment turn a
   single email/username into dozens of account nodes in one pass.
2. **Inputs cross-link** — the same site reached by email *and* username collapses to
   one node with multiple edges (convergence), visibly tying identities together.
3. **Facts leak from many places** — per GRAPH.md §13b, location from IP, EXIF,
   phone, and Google reviews each draw their **own** node → the viewer sees the same
   home city exposed four different ways. That repetition is the gut-punch.
4. **Streaming** (next build) makes all of the above *appear in real time*.
