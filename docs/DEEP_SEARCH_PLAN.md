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

### Provider/legal decision (2026-06-22)

Decision recorded after pricing + signup due-diligence on the three picks. Three things settled:

**1. Legal-exposure ranking (this drives tier placement):**

| Provider | Legal exposure | Why |
|---|---|---|
| **Optery** (removal) | **Lowest** | Consumer-rights/removal service acting *for* the user on *their own* data. Via API we become a data processor → need a DPA, but the use case is squarely legitimate. |
| **PDL** (enrichment) | **Middle** | GDPR Art. 14 territory (processing third-party data the subject didn't give us); PDL has prior data-exposure history. Real EU exposure, below skip-tracing. |
| **Endato/Enformion** (people-search) | **Highest — FCRA-gated** | Skip-tracing corpus. ToS prohibit FCRA-covered uses without vetting; disambiguating with it means pulling records about *other* people = the tracking surface. **Extended/admin tier only, behind the ownership gate.** |

**2. Name + address can NOT unlock the extended dossier for regular users.** The extended
*dossier* tier (address/relatives/age) reaches regular users **only through a magic-link-verified
email *seed*** (`OWNERSHIP_VERIFICATION.md` — "extended = username + verified linked email"). It is
*not* reachable via name+address matching, because:
  - Name+address is **forgeable** — it is byte-for-byte the *stalker's* input (an attacker knows
    the victim's name and address). Only **data co-occurrence with a verified seed** is trickproof;
    an assertion never is. (Same reason username can't be a seed.)
  - The harm is the **aggregation**, regardless of whose data it is — verifying a match doesn't make
    building the dossier safe; it just confirms the input.
  - This is also why ID/document upload is rejected (`OWNERSHIP_VERIFICATION.md:64`): ID proves legal
    name, not *which record is yours*, and adds special-category-data liability to a privacy tool.

  So: extended search is *not* permanently off-limits to regular users — but the unlock is the
  **email-seed gate**, never name+address. The **broker *removal*** feature is the exception that
  *is* normal-tier (name+address as removal targets → self-disambiguated listing existence → opt-out;
  bounded because broker data is already cheaply public + audit-log + rate-limit).

**3. Acquisition reality (what's obtainable, as an individual, now):**
  - **Optery** — API is **apply-only / quote** (B2B). Not obtainable now; **apply, defer until a paid
    tier funds it.** Free *consumer* exposure scan works for an individual today (use to vet coverage).
  - **Endato** — self-serve in theory, but signup needs a **US phone number + company**. **Not
    obtainable as a non-US individual.** Keep as the extended/admin pick for if/when there's an entity.
  - **PDL** — self-serve, individual-friendly (no company required), but signup is currently flaky
    (500 on account creation). Retry / different browser / contact support. Still the free real-data
    dev path once an account exists.
  - **Onerep** — removal alternative, ~870+ brokers, but the API is also **B2B/partner (apply)**.

**Net pick:** broker *removal* is the genuinely user-valuable feature, and the clean self-serve
individual path for it does not currently exist (all real removal APIs are apply-only B2B). So:
ship the **mock shim** for the test build, **apply for Optery** for the launch removal tier, keep
**Endato** parked for the gated dossier tier (needs a US entity), and use **PDL free** as the
dev-time real-data source once its signup works.

### What shipped instead of the mock shim (2026-06-22)

Re-evaluation after the providers turned out unreachable (Enformion needs a US phone+company,
PDL now needs a work email, Optery/Onerep are B2B apply-only). Two things settled:

**1. Extended *name* dossier (address/relatives/age) is currently UNBUILDABLE — parked.** Every
source that returns dossier data is walled to a non-US individual, and the only alternative
(scraping Spokeo-style sites) is both fragile and the exact "pull an arbitrary person's record"
surface the self-audit hard rule forbids. The `name_extended` seam stays in place for when a US
entity / paid provider exists; until then admins get nothing extra from a *name* (they still get
the gated extended tier from username+verified-email — that path is unaffected).

**2. The removal tier shipped FREE, no key — and it's honest by construction.** The removal track
("here are the people-search sites + the opt-out link for each") never needed a paid lookup. New
free provider `PeopleSearchRegistryProvider` (`name_providers.py`) enumerates a curated catalog of
~30 consumer people-search brokers (`connectors/data/people_search_brokers.json`, regenerated by
`scripts/refresh_broker_registry.py`), each with its opt-out URL, cross-referenced against the
public **California Data Broker Registry** (~580 brokers, live under the Delete Act) to stamp an
authoritative `ca_registered` flag. It is *enumeration, not confirmation*: it does NOT claim the
searched name is listed anywhere. The new provider attribute `confirms_listings = False` makes the
connector mark every signal `confirmed: false`, the clustering escalate-reason tells the judge to
frame it as a removal checklist (not proven exposure), and the report shows the opt-out links + the
CA-registered provenance. Default-on (`ARESCOPE_BROKER_REGISTRY_ENABLED`, free bundled data), so a
name-only scan is now *covered* (no more coverage gap) with a real removal artifact. A paid
confirming provider (`GenericRestNameProvider`, `confirms_listings = True`) still takes precedence
if ever configured — it upgrades these to confirmed individual hits without any connector change.

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
   `name_extended` seam for the gated dossier tier. **Normal/removal tier is now LIVE for
   free** via `PeopleSearchRegistryProvider` (curated people-search catalog + CA-registry
   provenance, `confirmed:false` enumeration → T1 removal artifact; see "What shipped"
   above). Remaining: the *extended dossier* tier stays parked (unbuildable without a US
   entity / paid provider) — flip it on if/when one exists and the ownership gate lands.
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
