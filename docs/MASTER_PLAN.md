# Arescope — Master Plan & Build Procedure

> The top-level sequence everything else serves. Phase docs: `ROADMAP.md` (phases),
> `EXTENDED_SEARCH_SCOPE.md` (the search engine), `OWNERSHIP_VERIFICATION.md` (the user
> gate), `DISTRIBUTION.md` (cost/launch). Last updated 2026-06-23.

## The procedure (do these in order — do not jump ahead)

**Phase A — Build the admin engine, as powerful as possible.** *(current)*
Make the most capable self-search an *individual* can build: maximum coverage, maximum
depth, everything wired for the **admin** tier with no user-facing limits yet. This is a
pure information-gathering system right now — farm every signal a single input (name /
email / username / IP / photo) can yield about the person who owns it. Mark broad/sensitive
sources `admin_only`; **do not** build per-user gating or worry about tier-splitting yet.
Push until we hit a real capability limit (no more obtainable tools / data).

**Phase B — Decide the user tier.** Only once Phase A stands: walk every function and
decide what a *regular, non-admin* user gets and how — gated by the per-input ownership
verification (`OWNERSHIP_VERIFICATION.md`). This is where the self-audit hard rule becomes
an enforced control rather than an admin-only convention. Tier-splitting is cheaper and
better-informed once the full capability set exists.

**Phase C — Design.** Make it look and feel like a real product (the impeccable/frontend
work): the report, the exposure map, onboarding, the input form, empty/coverage states.

**Phase D — Launch.** Wire the distribution/cost model (`DISTRIBUTION.md`), the paywall
tiers, deploy behind the shared nginx. Public users only after Phase B's gate exists.

## Why this order

Capability first (it's the moat + the portfolio proof + the thing we're curious about),
then productize the access controls, then polish, then ship. Building the gate or the UI
before the engine is finished would mean redoing both as the engine grows.

## Phase A status (2026-06-23)

**Live:** name→broker-removal catalog (free, CA-registry-backed); email→breaches/stealer/
accounts (HIBP/HudsonRock/Holehe); email→Gravatar identity + linked handles; username→
GitHub identity + Maigret-metadata; ip→Shodan; name→Brave web mentions (admin, validated).
GHunt (email→Google photo/locations) built + creds dropped, **pending live validation**.
Per-connector `admin_only` gate in place.

**Remaining Phase-A queue:** LinkedIn (ScrapIn/Apify, admin-only/own-profile) → Dehashed
(plaintext breach: name/phone/home address — richest universal data) → Apify (Instagram) →
photo input + EXIF/GPS → FaceCheck (reverse face). All config-gated drop-ins except EXIF.

See `aresis-build-strategy` (memory) for the directive and `EXTENDED_SEARCH_SCOPE.md` for the
per-connector detail + keys-to-acquire.
