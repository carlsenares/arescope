# Arescope — Findings Taxonomy, Severity Model & Remediation

This is the core of Arescope: the map from *what a source can surface* → *how dangerous it is*
→ *what fix helps*. The LLM judge classifies each piece of evidence into one of these
categories and assigns a severity using the rubric below; the remediation engine looks up
the fix track for the category + severity.

## Severity model

Severity is a function of four dimensions, scored by the judge:

| Dimension | Question |
|---|---|
| **Takeover potential** | Can an attacker use this to log in / impersonate / take over an account *now*? |
| **Data sensitivity** | How sensitive is the exposed data? (password > home address > phone > email > username) |
| **Recency** | How fresh is it? A 2012 breach password you've since rotated ≈ harmless; a 2025 infostealer log ≈ live. |
| **Exploitability** | How easily can this be turned into an attack? (default-cred RDP on a public IP = trivial) |

Levels:

| Severity | Meaning | Example |
|---|---|---|
| **Critical** | Enables account takeover or device compromise *right now*. | Plaintext/recent creds in a breach; active session cookies in an infostealer log; public service with default creds. |
| **High** | Strong attack enabler; fixable but urgent. | Cracked reused-password hash; exposed RDP/DB/admin panel; doxxable home address on a broker. |
| **Medium** | Privacy/footprint exposure enabling *targeted* attacks (phishing, deanonymization). | Account enumeration across many sites; data-broker listing; public Google profile linkage. |
| **Low** | Minor footprint, low actionability. | Username reused on a few platforms; email in an ancient email-only breach. |
| **Info** | Neutral context, no action needed. | "This email has a Spotify account." |

## Category → source → severity logic → remediation

| # | Category | Surfaced by | What it means | Severity logic | Remediation (tier) |
|---|---|---|---|---|---|
| 1 | **Credential exposure** | HIBP, Dehashed | Email/password appears in a breach corpus; password may be plaintext or a crackable hash. | Critical if plaintext + recent or password reused on important accounts; High if hash/cracked; Low if old + already rotated. | Change the password everywhere reused; enable 2FA; adopt a password manager; per-breach guidance. **T0 guided + T1** (generate the "change these N accounts" checklist). |
| 2 | **Infostealer infection** | Hudson Rock (Cavalier) | The user's *device* was infected; credentials + session cookies + autofill were exfiltrated. | Always Critical — implies live session theft and mass credential loss. | Run a malware scan; rotate **all** passwords; invalidate active sessions everywhere; revoke OAuth grants. **T0 guided**, high priority. |
| 3 | **Breach membership** | HIBP | Email is in breach(es); exposed data types vary (password, address, phone, DOB). | Scales with data type: password→High, address/phone→Medium, email-only→Low. | Per-breach: rotate creds, watch for phishing, freeze credit if SSN/financial. **T0 + T1** (per-breach action list). |
| 4 | **Account footprint** | Holehe / user-scanner, Maigret | Which sites an email/username is registered on (often without alerting the target). | Medium (enables targeted phishing + deanonymization); higher if it links a "private" identity to a real-name one. | Delete unused accounts; use email aliases per service; separate pseudonymous vs real identities. **T0 + T1** (draft account-deletion requests). |
| 5 | **Account/identity metadata** | GHunt, Epieos | Public Google/account data: display name, photo, linked services, public reviews/Maps/calendar. | Low–Medium (deanonymization, social-engineering fuel). | Tighten Google privacy settings; remove public reviews/maps contributions; scrub profile photo reuse. **T0 guided.** |
| 6 | **Exposed infrastructure** | Shodan, Censys | Open ports / exposed services on an IP the user owns (RDP, databases, cameras, routers, NAS), plus known CVEs. | Critical if default-cred/known-CVE admin service is reachable; High for any exposed sensitive service; Medium for informational banners. | Close the port / firewall it; patch; change default creds; put behind VPN. **T0 guided** (this is the most "security" of the categories). |
| 7 | **Data-broker / people-search listing** | name + people-search sources | Home address, phone, relatives, age listed on broker/aggregator sites. | High if home address is public (doxxing/swatting risk); Medium otherwise. | Submit opt-out/removal requests to each broker. **T1 artifact (generate the requests) → T2/T3 automation** — this is the one category where *automated submission* is realistic and valuable (the Incogni/DeleteMe model). |
| 8 | **Username correlation** | Maigret, Sherlock | The same username across many platforms lets anyone correlate activity into one profile. | Low–Medium (deanonymization). | Vary usernames across contexts; retire the linking handle. **T0 guided.** |
| 9 | **Face / photo exposure** | Pimeyes/FaceCheck (DEFERRED) | A photo of the user appears on other sites/profiles. | Medium–High (stalking, deanonymization, impersonation). | Takedown requests; remove source photo; tighten profile visibility. **T1 artifact.** *(Deferred — no official API, ToS bars automation; integrate manually or in a later phase.)* |

## Remediation automation tiers (what's actually buildable)

| Tier | What it is | Feasibility | Phase |
|---|---|---|---|
| **T0 — Guidance** | Exact steps + deep links ("change password here", "close this port", "enable 2FA here"). | Easy, always works. | P1 (MVP) |
| **T1 — Generated artifact** | Auto-draft the GDPR/CCPA deletion email, broker opt-out request, or takedown letter for the user to send. | Easy. High value. | P1.5 |
| **T2 — Assisted flow** | Pre-filled opt-out forms; one-click deep-links into broker removal portals. | Medium. | P2 |
| **T3 — Automated submission** | Arescope submits the opt-out/removal on the user's behalf (with permission). | Hard but viable **for data-broker opt-outs specifically** (#7). Avoid for arbitrary account changes — fragile, CAPTCHA/ToS/credential-liability. | P2+ (scoped to #7) |

**Design implication:** every `finding` gets a `remediation` with a `tier`. P1 ships T0+T1
for all categories. Automation (T2/T3) is added later and *only* where it's safe and
valuable — chiefly the data-broker opt-out loop. "Automatic fixes after permission" is a
real goal, but its honest scope is *deletion/opt-out requests*, not logging into the user's
accounts and changing settings.
