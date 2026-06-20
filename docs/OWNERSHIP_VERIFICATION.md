# Arescope — Ownership Verification (anti-abuse)

Arescope is a **self-audit** tool. The single thing that keeps it from being a
people-search / stalking tool is the **ownership gate**: you only ever get
information about identities you can prove are yours. This doc is the final model.
It's a no-op in P0 (operator asserts ownership) and becomes mandatory as the
pluggable `VerifyOwnership` strategy in P2 (`ARCHITECTURE.md` §4.2).

## Why gate at all, if the underlying tools are public?

HIBP, Maigret, Hudson Rock and Shodan are each usable without proof. We gate
because **the harm is the aggregation, not the single lookup**: Arescope combines
those sources, builds an identity graph, runs an LLM that synthesizes a readable
dossier, and proposes actions. By hand that takes skill and an afternoon;
unguarded, we'd turn it into one click. The gate doesn't try to prevent what's
possible elsewhere (a determined attacker uses the raw tools, and then *they* did
it) — it keeps **us** from being a people-search operator, removes the
casual-abuse easy button, and lets us honestly call it self-audit.

**Design rule:** strictness scales with *how much non-public harm an input
unlocks*. Infostealer logs and handle de-anonymization (not cheaply public) are
strict; data-broker listings (already a $5 public purchase) are looser.

## The core model: seeds vs. filters

A username is not an ownable global identifier — the only thing any proof can
establish is "I control account-with-handle-H on platform-Y right now," never "H
is mine across the internet." So we split inputs:

- **Seeds** — provable ownership, *key* a search:
  - **email** → verified by **magic-link / OTP** (control = receiving mail; the
    only proof that fits an email — no public profile to inspect).
  - **ip** → verified by **source-IP match** (we only scan the IP you're
    connecting from) **and residential/mobile only** (IP→ASN→usage-type via
    IPinfo/MaxMind; datacenter/hosting/VPN excluded for a personal audit).
    Misclassification (e.g. a VPN user) is a *benign block*, never a stranger scan.
- **Filters** — refine/label seeded results, *never* seed a search:
  - **username**, **name**.

### How username works without becoming a stalking tool

Username findings are surfaced two safe ways, never by bare enumeration of a
user-typed handle:

1. **Derived from a seed (the main path).** When the verified email's records
   (HIBP / Hudson Rock / Epieos) *contain* a username, that handle is corroborated
   to the user. We can then safely pivot — e.g. run Maigret on that derived handle
   to map the user's *other* accounts — because an attacker can't fabricate a
   breach record linking *their* verified email to a *victim's* handle. Residual:
   handle collisions surface a stranger's account → flagged "we think this is
   yours; confirm" (a contingency question).
2. **Strict co-occurrence (user supplies username + email).** A user-typed
   username only yields findings where that handle and the verified email *actually
   appear together* in real evidence. Un-trickable: renaming an account doesn't
   help, because the data — not the assertion — proves the link.

OAuth / bio-token only ever *confirm a specific account you control*; they do not
license bare enumeration. (Multi-email reality: verifying email A shows the A-half;
the B-half needs email B verified — run per combo.)

### Name

Filter only — disambiguates results already anchored to a seed ("which John
Smith"). Never seeds a search. **No ID/document upload** — antithetical to a
privacy tool, and ID proves your legal name, not *which* leaked record is yours,
so it doesn't even solve the problem.

### Data brokers (#7) — the one looser category

Brokers (Spokeo, WhitePages, Radaris, Acxiom…) are keyed on name + location, which
email can't reach. So this is a distinct **removal-oriented** feature, not a
people-search seed: the user supplies name + address as *removal targets*, the
output is self-disambiguated (you recognise your own listing), and the action is
**opt-out**. Abuse is bounded because broker data is already cheaply public (low
marginal harm), and a per-account **audit log + rate-limit** is the compensating
control. We surface + generate the opt-out artifact; we do not try to out-cover
the dedicated removal services (Incogni/DeleteMe/Optery) — see `POSITIONING.md`.

## Accountability layer (enables the looser bits)

A verified-identity account behind every search, a minimal **audit log**
(who-searched-what, on the retention TTL), rate-limits, and anomaly flagging (one
account fanning out across many distinct names/handles = the stalking signature).
This is a *detective* control, not preventive — its job is to let us safely loosen
(brokers, derived-pivot) while staying accountable. Logging is itself a privacy
cost, so keep it minimal and TTL'd.

## Residual gaps (accepted)

- **Lost-email + username only:** if the only proof-bearing channel is gone, a
  non-ownable handle can't be searched safely — that request is byte-for-byte a
  stalker's. Accepted. (Active-threat findings stay reachable via *any* email seed
  the user can still verify.)
- **Pseudonymous handle, no email:** identical to a stalker's de-anonymization
  query; for that exact request the feature would help the attacker more than the
  owner (who already knows their own accounts). Not offered.

## Error UX — explain, don't just block

Every blocked input / failed verification shows a **specific reason** + an **ⓘ**
linking to a *"Why Arescope verifies inputs"* page. Example:

> **Can't run this IP scan.** `203.0.113.10` belongs to a hosting/VPN provider.
> Personal audits only cover the residential connection you're currently using.
> ⓘ Why? → /about/verification

Both UX and the public statement of the project's ethics.
