# Extended Search — Exact Scope & Connector Plan

> The "go big" identity-enrichment phase: turn shallow enumeration (where a handle
> exists) into depth (what it reveals — name, photo, locations, posts). Pairs with
> `DEEP_SEARCH_PLAN.md` (tiers/safety frame), `OWNERSHIP_VERIFICATION.md` (the gate),
> `FINDINGS_TAXONOMY.md` (severity), `DISTRIBUTION.md` (cost). Last updated 2026-06-22.

## Decisions (2026-06-22)

- **Budget: free-only for now.** Build the free connectors live; design every paid
  source as a **config-gated drop-in** (key absent ⇒ coverage gap, never a failure —
  same pattern as HIBP/Shodan). No paid keys acquired yet.
- **Face search: admin-only**, and it's a paid drop-in (FaceCheck.id). Never on the
  user tier; audit-logged when it runs.
- **Email-seed unlock: admin-first.** Prove the full pipeline ungated for admin, then
  wire the user-tier gate (the `OWNERSHIP_VERIFICATION.md` email seed) before any real
  users. Matches the `DEEP_SEARCH_PLAN.md` dev reality.

## The model

**Normal tier — seeded by ONE verified email.** The unlock is **data co-occurrence,
not user assertion** (the trickproof rule, `OWNERSHIP_VERIFICATION.md`): we never ask a
user to assert a username (forgeable); we *discover* handles that co-occur with the
verified email and only then pull their public detail.

```
verified email (seed)
  ├─ its public identity   → Gravatar + GHunt(Google): real name, profile PHOTO, Maps reviews (locations)
  ├─ its breach/stealer    → HIBP / Dehashed / Hudson Rock                 (already built)
  ├─ its account map       → Holehe                                        (already built)
  └─ DISCOVERED handles    → the GitHub/Google/Gravatar account tied to that email
        └─ unlock those handles' public POSTS / PICS / LOCATIONS (Maigret-meta, GitHub, Reddit)
```

**Admin tier — same engine, gate off, any input** (name/username/email/IP/photo), plus
the heavy/sensitive sources (web-mention search, locked-platform scraping, leak corpora,
reverse face). These stay admin-only because on the user tier they'd breach the
self-audit hard rule; they are audit-logged.

## Connector menu

### Build now — free (no key, or free tier / free monthly credits)

| Connector | Input → reveals | Source | Notes |
|---|---|---|---|
| **Maigret metadata** | username → name, location, avatar URL, bio, followers | Maigret JSON we already fetch (only existence used today) | biggest depth-per-effort; feeds photo+location graph nodes |
| **GitHub** | username/email → name, location, company, bio, commit-emails, activity | `api.github.com` (free token) | richest for devs |
| **Reddit** | username → posts/comments, subreddits, karma, location tells | `/user/{u}.json` (free OAuth) | behavioural + location leakage |
| **Gravatar** | email → avatar, display name, linked profiles | gravatar.com (no key) | the normal-tier PHOTO, from the verified seed |
| **Photo EXIF** | uploaded image → GPS, device, timestamp | local parse (Pillow/exifread) | $0, high-impact; needs the photo input added to the form |
| **Wayback** | name/username/url → deleted / historical profile versions | archive.org (free) | "what you thought you removed" |
| **GHunt** | email → Google identity: profile PHOTO, Maps reviews (locations), YouTube | free, self-hosted | **install isolated (`pipx install ghunt`) — it pins httpx<0.28 and conflicts with the app**; auth via `ghunt login` (browser + GHunt Companion extension + a burner Google account) → creds at `~/.malfrats/ghunt/creds.m`; point `ARESCOPE_GHUNT_CREDS_PATH` at that file; fragile, name unreliable since 2024 |
| **Brave Search** (admin) | **name** → web/news/court/social mentions | Brave Search API | $5 free credit/mo covers dev; owns its index (no scrape-legal exposure) |
| **Apify** (admin) | username → locked-platform public posts/pics (IG/TikTok/LinkedIn) | Apify actors | $5 free credit/mo; public surfaces only, no login bypass |

**GHunt-vs-Epieos decision (2026-06-22):** the Google-identity piece is the email-seed core
(name + photo + Maps-review locations). **Epieos' API is request/quote-only** (Pro/Elite, contact
sales) — as an individual we likely won't be approved, so it is NOT a reliable path. **GHunt is
the free substitute** for the highest-value slice and needs no approval; its costs are fragility
(Google changes break it — pin the version) and a Google session cookie the operator supplies
(fine admin-first; a public-service problem we defer). **Epieos stays a paid fallback only if ever
approved.** The other ~140 Epieos sites overlap Holehe/Maigret, so we lose little.

### Paid drop-ins — design now, key later (config-gated)

| Connector | Input → reveals | Acquire | ≈ Cost | Tier |
|---|---|---|---|---|
| **Dehashed** | email/name → breach + plaintext credential depth | self-serve instant | low PAYG | both |
| **IntelX** | email/name/domain → leaks, pastes, darkweb, leaked docs | self-serve, yearly sub | sub | admin |
| **FaceCheck.id** | **photo** → reverse face search across the web | self-serve (crypto) | ~$0.30/search | admin-only, audit-logged |
| **TinEye** | photo → profile-pic reuse across the web (links pseudonymous accounts) | self-serve | PAYG | admin (lighter face alternative) |
| **Epieos** | email → Google + 140 sites (stable hosted GHunt alternative) | **request-only API — approval unlikely** | €30/mo+ | only if approved; GHunt covers it otherwise |

Out of scope: **PimEyes** (no real API), **X/Twitter API** (locked/expensive), **SerpAPI**
(Google litigation — prefer Brave), paid people-search dossier APIs (US-entity-walled,
`DEEP_SEARCH_PLAN.md`).

### Keys / credentials to acquire (the "drop them in later" list)

| Env var | Tool | Status | Needed for |
|---|---|---|---|
| *(none)* | Maigret-meta, GitHub, Gravatar | **live, no key** | the free identity core |
| `ARESCOPE_GITHUB_TOKEN` | GitHub | optional | raises rate limit 60→5000/hr (unauth works) |
| `ARESCOPE_REDDIT_CLIENT_ID` / `_SECRET` | Reddit | **needed to return data** | Reddit now 403-blocks unauth from servers; free "script" app fixes it |
| `ARESCOPE_GHUNT_CREDS_PATH` | GHunt | **built (unvalidated)** — needs `ghunt login` cookie | Google identity: photo, Maps-review locations, YouTube |
| `ARESCOPE_BRAVE_API_KEY` | Brave Search | **built** — needs free key | name → web mentions (admin-only) |
| `ARESCOPE_APIFY_TOKEN` | Apify | not built yet (free credits) | locked-platform posts/pics (admin) |
| `ARESCOPE_DEHASHED_API_KEY` | Dehashed | not built yet (paid) | credential depth |
| `ARESCOPE_INTELX_API_KEY` | IntelX | not built yet (paid) | leaks/pastes (admin) |
| `ARESCOPE_FACECHECK_API_KEY` | FaceCheck.id | not built yet (paid) | reverse face (admin) |
| `ARESCOPE_SCRAPIN_API_KEY` | ScrapIn (LinkedIn) | not built yet (paid) | email/name → LinkedIn profile (admin-only / own-profile) |

### Build status (2026-06-23)

**Shipped + validated live:** GitHub (username → name/location/company/photo/linked
handles), Gravatar (email → name/location/photo + discovered linked accounts — the
co-occurrence seed in action), Maigret-metadata (profile `ids` → identity attributes).
New `identity_attribute` signal wired through clustering (→ ACCOUNT_METADATA / FACE_PHOTO_
EXPOSURE), the exposure graph (photo + location nodes), and the report. Config flags added
for every drop-in. **Reddit** built but needs a free OAuth app (see above) — without it the
connector reports an honest coverage gap (it no longer pretends "no account").

**Added 2026-06-23 (universality pass):** the email/name anchors everyone has, not just devs.
**GHunt** (email → Google photo + Maps-review locations + YouTube) — built, config-gated on a
Google cookie, defensive JSON parsing, *unvalidated end-to-end* (no cookie here; name retrieval
is unreliable upstream since ~2024 but photo/Maps land). **Brave Search** (name → public web
mentions) — built, key-gated, **admin-only**. New `web_mention` signal → ACCOUNT_METADATA. Added
the **per-connector admin gate** (`Connector.admin_only`; the service drops admin-only sources
for non-admins) — the mechanism the heavy sources needed.

**Provider correction:** Proxycurl (email→LinkedIn) was sued by LinkedIn and shut down Jul 2025.
LinkedIn successors that are self-serve: **ScrapIn** (email/name → full profile) or **Apify**
LinkedIn scraper. LinkedIn is greenlit as **admin-only / own-profile**, audit-logged — build next.

**Not built yet:** photo-input+EXIF, LinkedIn (ScrapIn/Apify, admin-only), Apify (Instagram),
Dehashed (plaintext breach: name/phone/address — the richest universal data), IntelX, FaceCheck/
TinEye.

## Per-input summary (admin, no gate)

- **email** → breaches+stealer+accounts (have) · Gravatar/Epieos identity · Dehashed · IntelX · discovered-handle unlock
- **username** → Maigret existence (have) + **metadata** · GitHub · Reddit · Apify locked-platform · Wayback
- **name** → broker removal catalog (have) · Brave web-mention search · IntelX
- **ip** → Shodan host+services (have)
- **photo** *(new input)* → EXIF · FaceCheck/TinEye reverse search

## Build order

1. **Maigret metadata mining** — free, large depth gain, no new keys. Parse the JSON we
   already fetch into name/location/avatar graph nodes.
2. **GitHub + Reddit connectors** — free, own-account posts/location.
3. **Gravatar + GHunt + the email-seed co-occurrence unlock (admin)** — verified-email →
   Google/Gravatar identity (name/photo/locations) → discovered handle → feed (1)/(2).
   Proves the moat ungated. GHunt is config-gated on a Google-cookie path.
4. **Photo input + EXIF** — add the photo field to the form; local metadata parse.
5. **Brave + Apify (admin)** — web mentions + locked-platform public posts, on free credits.
6. **Paid drop-ins** — Dehashed → IntelX → FaceCheck/TinEye, each behind its own
   `ARESCOPE_*` key; ship dark, activate per funding decision. (Epieos only if approved.)
7. **User-tier gate** — wire the `OWNERSHIP_VERIFICATION.md` email seed; flip the
   admin-only co-occurrence unlock on for verified users.

## Safety / legal notes

- **Admin-only sources** (Brave/Apify/IntelX/FaceCheck/TinEye) never run on the user tier
  and are audit-logged — they cross the line the self-audit hard rule guards.
- **Removal artifact picks statute by jurisdiction**: GDPR (EU/UK) does not generally reach
  US brokers for US residents; US users get CCPA/CPRA + the Delete Act DROP platform (live
  2026) + state-law deletion. Feed the LLM the user's jurisdiction (it already drafts both).
- **Co-occurrence, never assertion** for the handle unlock (forgeability — the stalker's
  input is name+handle). Same reason name+address can't unlock the dossier.
