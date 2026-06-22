# Deep Search & Enrichment — Roadmap & Provider Plan

> Forward-looking plan for the remaining "the system feels shallow" feedback (#7
> depth, #7 extended identity search, #12 admin any-IP). Pair with `ROADMAP.md`
> (phases), `TOOLS.md` (connectors), `OWNERSHIP_VERIFICATION.md` (the gate this
> depends on), `DISTRIBUTION.md` (the cost story). Last updated 2026-06-22.

## The safety frame (read first)

Arescope is **self-audit only** (CLAUDE.md hard rule). Everything below is built
to help a user see and shrink *their own* footprint — never to investigate
others. The dividing line is **ownership verification**, not capability:

- **Username-only search → "safe" output.** Where the handle is registered, plus
  issues. No location/post/photo aggregation. Safe because it's the same
  enumeration anyone gets from a public profile list; it doesn't build a dossier.
- **Username + verified linked email → "extended" output.** Cross-reference the
  two, pull locations/posts/profile pics, build the richer identity graph. This
  is dossier-shaped, so it is **gated**: only runs when both inputs are present
  and ownership-verified (`OWNERSHIP_VERIFICATION.md`).
- **Admin bypasses the gate** (can audit anything — already true today).
- **Dev reality (2026-06-22):** single user, no public access, so extended search
  is being **built ungated for now** to evaluate it; the gate goes on before any
  real users. Do not ship extended search publicly without the gate.

## Current coverage (what each input gets today)

| Input | What we return now | Sources |
|---|---|---|
| **email** | breaches, infostealer-log hits, ~120 account registrations | HIBP, Hudson Rock, Holehe |
| **username** | site registrations (~3000 sites), infostealer-log hits | Maigret, Hudson Rock |
| **ip** | exposed services + CVEs, **geolocation + ISP/ASN/hostnames + open-port summary** | Shodan (host_profile + per-service) |
| **name** | data-broker / people-search **listing existence + opt-out links** (the removal track) when a provider is configured; honest coverage gap otherwise. Full dossier (address/relatives) is the gated **extended** tier (name + verified email), built next. | brokers (config-gated, provider-agnostic) |
| **photo** | nothing (not in the input form yet) | — |

The gaps the feedback is about: username is broad-but-shallow (no location/posts),
name has no source at all, email stops at Holehe's ~120 sites.

## Tiered provider plan

### Tier A — free, builds on what we already run (do first)

1. **Maigret metadata mining.** Maigret already fetches each matched profile and
   its JSON carries extracted fields for many sites — `ids` like full name,
   location, avatar/image URL, follower counts, bio. We currently use only
   *existence* (site yes/no). Parsing these gives real identity enrichment —
   names, locations, **profile-pic URLs** — at **$0**, from the user's own public
   profiles. Biggest bang for the least cost; partially satisfies "profile pics"
   and "locations connected to apps".
2. **Public-API social connectors (own, verified accounts).** Targeted, high-signal
   platforms with free public APIs:
   - **GitHub** (`api.github.com/users/{u}`): name, location, bio, company, repos,
     recent public activity.
   - **Reddit** (`/user/{u}.json`): public posts/comments, subreddits, karma.
   - (Optional) Hacker News, Mastodon — all free, public.
   These deliver "public posts / locations connected to apps" without scraping or
   paid keys, for the platforms most likely to leak real-world detail.
3. **Richer IP geo (optional).** Shodan already gives geo; ipinfo/MaxMind free tier
   can fill in when Shodan is sparse. Low priority — IP enrichment already shipped.

### Tier B — paid, staged (the ~$300/mo OSINT floor; gate behind tiering)

Per `DISTRIBUTION.md`, the real cost threat is the fixed OSINT subscription floor,
not per-scan LLM. Add these as paid tiers unlock, not all at once:

- **Dehashed** — deepest credential/breach corpus (#1). The strongest single paid
  add; turns "you're in N breaches" into "here's the exposed password/field".
- **Epieos / GHunt** — email → Google account metadata: display name, profile
  photo, linked services, public Maps reviews (#5). GHunt is free but fragile;
  Epieos is paid but stable. Currently deferred (see handoff: free path chosen).
- **Data-broker source (#7 name)** — home address, phone, relatives, age on
  people-search/aggregator sites. No clean cheap API; options are a paid
  people-search aggregator or targeted broker scraping (fragile, breaks often).
  The **legitimate** use is surfacing the user's *own* listing → the T1 opt-out /
  removal artifact we already generate. This is the most ethically loaded source —
  gate hard, frame strictly as removal.

### Name-search providers (the #7 data source) — free test vs paid launch

The name connector is provider-agnostic (`connectors/name.py` + `name_providers.py`); this is
the provider menu. Prices ≈2025/early-2026, **verify** — most B2B ones are quote-based. Two
product categories map onto our two tiers:

- **Removal-oriented "exposure scan"** → our **normal tier** (listing existence + opt-out →
  T1 removal). Cleanest fit for the self-audit hard rule: these exist to find+remove *your*
  listings.
- **People-search / enrichment** → our **extended/admin tier** (the dossier: address,
  relatives, age). The capability we gate behind ownership.

| Provider | Category | Returns | Self-serve API | Free tier | ≈ Price |
|---|---|---|---|---|---|
| **Optery** | removal | where you're listed across ~300+ brokers, screenshots, opt-out | Business API (apply) | free consumer scan | consumer $3.99–$25/mo; API quote |
| **Onerep** | removal | ~200 broker listings + removal status | partner API | — | quote (B2B) |
| **DeleteMe** | removal | broker listings + managed removal | business API | — | consumer ~$129/yr; API quote |
| **People Data Labs** | enrichment | name→location/job/socials/contact | ✅ self-serve | ~100 matches/mo | ~$0.01–0.28/match |
| **Endato** | people-search | addresses, phones, relatives, age | ✅ self-serve PAYG | trial credits | ~$0.10–0.50/lookup |
| **Enformion** | people-search | addresses, relatives, associates | apply | — | quote, mid |
| **Pipl** | investigative | deep identity dossier | enterprise | — | expensive, min commitments |
| **Ekata (Mastercard)** | verification | name/address/phone/email correlation + risk | enterprise | — | quote |
| **TLOxp / IDI (TransUnion)** | investigative | full dossier | **gated (permissible purpose)** | — | restricted — not for self-serve self-audit |

**Constraints that decide it:**
- *FCRA / permissible purpose* — TLOxp, Pipl, and the deeper Enformion/Endato data are built
  for KYC/skip-tracing and gate access behind business vetting + a permissible purpose.
  Auditing your *own* name is legitimate, but these are friction to self-serve and add
  compliance overhead if shipped to end users.
- *Self-audit hard rule* — the removal providers (Optery/Onerep/DeleteMe) match it verbatim;
  the investigative people-search APIs are the dossier engine we keep behind the ownership gate.

**Picks:**
- **Free, for the test build now:** a local **mock shim** (a ~30-line endpoint answering the
  adapter contract, exercises the whole pipeline) or **People Data Labs** free tier (map its
  `data[]` into the listings contract).
- **Normal tier + removal at launch:** **Optery** (free consumer scan to vet coverage first) or
  Onerep — native "where you're listed" + opt-out.
- **Extended/admin dossier at launch:** **Endato** (cheapest self-serve PAYG, easy to wire);
  Pipl only if depth justifies the cost + commitment.

Each maps into the existing adapter contract via a thin shim — no connector change.

### Tier C — deferred (heavy cost / breakage / ethics)

- **PimEyes / reverse face search** (#9 photo) — paid, privacy-heavy. Defer.
- **Locked platforms** (Instagram/TikTok/Facebook) — need scraping or paid
  aggregators; high maintenance. Defer.

## Recommended build order

1. **Maigret metadata mining** (Tier A·1) — free, large depth gain, feeds the
   identity graph (location + photo nodes). *No new keys, no gate change.*
2. **GitHub + Reddit connectors** (Tier A·2) — free, own-account posts/location.
3. **Ownership-verification gate** (`OWNERSHIP_VERIFICATION.md`) — the prerequisite
   to expose extended search to real users. Until then extended search stays
   dev-only/ungated.
4. **Dehashed** (Tier B) — credential depth, first paid add.
5. **Data-broker (#7 name) + Epieos (#5)** — paid, staged with the paywall tiers.
   *Name connector scaffolding is now built* (`connectors/name.py` +
   `name_providers.py`): provider-agnostic, config-gated (`ARESCOPE_NAME_SEARCH_API_URL`
   / `_KEY`), normal tier = listing existence + opt-out → T1 removal artifact, with the
   `name_extended` seam for the gated dossier tier. Remaining: wire a concrete provider
   (or a thin shim) + flip extended on once the ownership gate lands.
6. **Admin any-IP** — already works via `/app/new`; only optional polish remains
   (a dedicated admin entry point + an "infiltration points" summary view). Not a
   capability gap.

## Notes for the next session

- Extended search (locations/posts/pics) is the moat (`aresis-positioning`), but
  it's also the line the hard rule guards — keep the gate dependency explicit.
- Tier A is the cheapest, safest, highest-leverage work and needs no provider
  decision — start there.
- Tiers B/C are real money + a provider choice; decide per `DISTRIBUTION.md`
  before wiring keys.
