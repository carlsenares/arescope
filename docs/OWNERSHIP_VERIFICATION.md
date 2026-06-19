# Aresis — Ownership Verification (anti-abuse)

Aresis is a **self-audit** tool. The single thing that keeps it from being a
people-search / stalking tool is the **ownership gate**: you can only scan an
identifier you can prove is yours. This doc defines how that proof works per
input. It's a no-op in P0 (operator asserts ownership) and becomes mandatory as
the pluggable `VerifyOwnership` strategy in P2 (`ARCHITECTURE.md` §4.2).

## Why gate at all, if the underlying tools are public?

HIBP, Maigret, Hudson Rock and Shodan are each usable without proof. So why add
friction? Because **the harm is the aggregation, not the single lookup**. Aresis
combines those sources, correlates across identifiers, runs an LLM that
synthesizes the result into a readable dossier, and proposes actions. By hand
that takes skill and an afternoon; unguarded, we turn it into one click.

The gate is therefore **not** trying to prevent what's technically possible
elsewhere — a determined attacker will go use the raw tools, and then *they* did
it. The gate exists to:

1. Keep **us** from *being* a people-search operator (legal, reputational, ethical).
2. Remove the **casual-abuse easy button** — almost all real abuse is low-effort
   and opportunistic (ex, coworker). Light friction filters those out while barely
   touching a legitimate self-auditor who actually owns the input.
3. Let us honestly call it self-audit.

**Design rule that keeps it easy:** verification strength scales with the
*marginal harm we add* and *how much the input exposes a third party*. Not every
field gets the same gate, and no unverified identifier may ever **seed** a scan.

## Fields are optional and independently verified

Every identifier is verified and scannable on its own — IP-only, email-only, etc.
There is **no universal email requirement**. The one coupling: scanning a
**username** requires a linked, verified email as a correlation anchor (a bare
username is the core stalking vector).

## Per-input verification

| Input | Tools → what they expose | Proof of ownership | Effort |
|---|---|---|---|
| **email** | HIBP, Holehe, Hudson Rock → breach creds, infostealer logs, site footprint | **Magic-link / OTP** sent to the address (control = receiving mail) | 1 click |
| **username** | Maigret, Hudson Rock → whole cross-site footprint from one handle | **OAuth** ("Connect account") — primary; **bio-token** fallback. Plus a linked verified email. | 1–2 clicks |
| **ip** | Shodan → exposed services / ports / CVEs of the host | **Source-IP match** (scan only the IP you're connecting from) **and residential/mobile only** | 0–1 step |
| **name** | *No connector consumes it yet*; future data-broker (#7) filter | **None — filter-only, never seeds a scan** | 0 |
| **photo/face** | (deferred) FaceCheck/Pimeyes → find-by-face | **Liveness selfie-match** only | (deferred) |

### Mechanisms in detail

- **Magic-link / OTP (email).** Standard. The only proof that fits an email,
  since an email account has no public profile to inspect. Covers Gmail et al.
- **OAuth (username — primary).** Google, GitHub, Microsoft, Reddit, Discord,
  Apple, LinkedIn, X all offer free OAuth. One click returns a cryptographically
  definite "this account is mine," usually with the verified email + handle. For
  Google/Microsoft it also satisfies the email proof. Cost: register an OAuth app
  per provider (basic profile/email scope — light).
  - *Honest limit:* OAuth proves the handle on **that provider**. Maigret may surface
    the same handle elsewhere that isn't the same person — results are framed
    "accounts matching your handle (some may not be you)."
- **Bio-token (username — fallback).** We issue a random token
  (`aresis-verify-<rand>`); the user pastes it into a **public profile bio**; we
  fetch the public page and confirm. Proves control because only the owner edits
  the bio. **Only works on platforms with a public, editable profile** (X, GitHub,
  Reddit, Instagram…) — *not* email accounts.
- **Source-IP match (ip).** The server already sees the IP you connect from; we
  only scan that one. Being *on* a network isn't owning it, so we additionally
  require the IP to classify as **residential/mobile** (IP→ASN→usage-type via
  IPinfo/MaxMind). Datacenter/hosting/VPN IPs are excluded — consistent with a
  personal audit, and the classification catches the datacenter case reliably.
  Misclassification (e.g. a VPN user) yields a *benign block*, never a stranger
  scan, and is explained in the error (below).
- **Name — no verification.** A name can't be owned and never seeds a search; it
  only disambiguates results already anchored to a verified email/username
  ("which John Smith"). No ID/document upload — that's antithetical to a privacy
  tool and unnecessary given filter-only use.

## Error UX — explain, don't just block

Every blocked input or failed verification shows a **specific reason** plus an
**ⓘ** linking to a *"Why Aresis verifies inputs"* page that explains the
self-audit philosophy. Example:

> **Can't run this IP scan.** `203.0.113.10` belongs to a hosting/VPN provider.
> Personal audits only cover the residential connection you're currently using.
> ⓘ Why? → /about/verification

This is both UX and the public statement of the project's ethics.
