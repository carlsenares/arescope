# Tooling evaluation — 2026-06-25

A pass over a batch of candidate tools/libraries (dev workflow, product, design,
security) + how each maps to Arescope. Decisions here feed the acquisition checklist
at the bottom. For OSINT *connectors* see `CONNECTOR_EXPANSION_PLAN.md` /
`EXTENDED_SEARCH_PLAN.md`; this file is everything that ISN'T a finding connector,
plus the content-extraction tools the identity map needs (which overlap both).

## The identity-map north star (drives the content-extraction picks)
> **"This is how much I can find out about you without any hard-to-get information."**

The map's whole point is the *shock*: the user types only **easy public seeds**
(email, phone, name, username, maybe a photo) and sees how much the open internet
infers about them. So:
- **No user uploads / "download your data" files in the map.** That's a different,
  more boring product ("here's what Instagram's export contains"). Parked as a
  separate future feature, explicitly NOT the map.
- The payoff is **public content that supports inference** — Instagram posts,
  LinkedIn employment/history, Google Maps reviews, tweets, public photos — not just
  "you have an account here." Reviews in one city ⇒ home city; gym check-ins ⇒
  routine; restaurant tastes ⇒ profile. The Opus **Evaluate** step (GRAPH.md §13)
  turns that content into the inferences that create the effect.
- This means the hard part isn't "find the profile," it's **extracting public
  content off walled/JS platforms** (IG/LinkedIn/Google) that have no clean API.

## Content extraction (the map's engine)

| Tool | What it is | Decision | Use case |
|---|---|---|---|
| **Crawl4AI** (github.com/unclecode/crawl4ai — this is "unclecode") | OSS, self-hostable LLM-ready web crawler → clean markdown | **Adopt** (self-host, free) | Generic public-page extraction: discovered personal sites, LinkedIn *public* pages, broker opt-out pages, name web-mentions. Default over Firecrawl (no per-call bill; open-core-friendly). |
| **Firecrawl** | Managed crawl/scrape API (JS render + anti-bot) | **Drop-in upgrade only** | Same job as Crawl4AI but paid + handles anti-bot for you. Wire only if self-hosted Crawl4AI proves too brittle on a given target. |
| **Browser AI agent** (browser-use / Playwright + LLM) | Drives a real logged-in browser session | **Build admin/demo-only now** | The *only* way to get the **logged-in view** of IG/FB/X/LinkedIn (public-but-login-walled content). Perfect for the founder's own check + the demo. **Does NOT scale on shared creds** (rate-limit/ban with many users) — production stays Apify-public + per-user-throwaway-session later. |
| **Apify** (already wired) | PAYG actors scraping public IG/LinkedIn/TikTok/X/Maps by profile URL | **Keep, central** | The scalable public-content backbone. Needs profile URLs → fed from PDL/Tavily/Gravatar/Maigret discovery. |
| **GHunt** (already wired) | email → Google account: photo + Maps reviews | **Keep** | Maps reviews = prime inference fuel. Needs a valid Google cookie. |

**Map pipeline shape:** seeds → **discovery** (PDL, Gravatar, Maigret, Sherlock, Tavily
→ candidate profile URLs) → **extraction** (Apify / browser-agent / GHunt / Crawl4AI
→ posts, reviews, employment, photos) → **inference** (Opus Evaluate → the "we can tell
you live in X, work at Y, eat Z" verdict). See GRAPH.md §13/§12.

## Dev workflow

| Tool | What it is | Decision | Notes |
|---|---|---|---|
| **CodeRabbit** | AI PR reviewer on GitHub | **Adopt** (free for public repos) | Visible, always-on PR review trail — looks professional to a repo reviewer (Epieos). Complements local `/code-review ultra`, doesn't replace it. |
| **Headroom** | OSS context-compression proxy for Claude Code/Codex | **Optional, skip for now** | Compresses *input/context* tokens (not output, not thinking). Real-but-capped upside; Anthropic prompt caching already absorbs much of it and it does nothing for extended-thinking (output) cost. Personal dev tweak, zero product value. |
| **Emergent** (emergent.sh) | Agentic full-stack app builder | **Skip** | Builds apps from scratch; overlaps Claude Code, useless on an existing opinionated codebase. |
| **LLM council skill** | Multi-model deliberation/vote | **Skip (core)** | We're deliberately single-provider (Anthropic) with a Haiku→Sonnet→Opus cascade + structured output. A council adds cost/latency for marginal gain. Maybe revisit for the hardest verdicts only. |

## Product / growth

| Tool | What it is | Decision | Notes |
|---|---|---|---|
| **PostHog** | OSS product analytics, session replay, feature flags | **Adopt at launch (park now)** | Session replay shows where users drop in the input flow; feature flags = clean paywall rollout. Generous free tier, self-hostable (open-core fit). No value pre-users. |
| **Remotion** | Programmatic video in React | **Low priority / marketing** | Per-user animated "your footprint" recap or landing demo. Differentiator, not core. |
| **Openscreen** | Dynamic/trackable QR-code API | **Skip** | No clear fit for a privacy self-audit tool. |

## Design

| Tool | What it is | Decision | Notes |
|---|---|---|---|
| **Anime.js** | Lightweight JS animation lib | **Use if needed** | Landing hero / map micro-interactions. Overlaps the `impeccable` design work; pull in per-need. |

## Security

| Tool | What it is | Decision | Notes |
|---|---|---|---|
| **Burp Suite** (Community = free) | Web-app pentest proxy/scanner | **Adopt for the hardening pass** | Test auth, CSRF, session cookies, and the PII-bearing routes on arescope.com before calling it "done" (portfolio quality bar). |

## NOT tools — domain knowledge
**RedLine, Vidar, Raccoon** are **infostealer malware families**, not integrations.
They're the stealers whose logs Hudson Rock surfaces. Value = naming the family in a
stealer-log finding's explanation/remediation ("RedLine harvested your saved browser
passwords from an infected machine") makes remediation concrete. Reference data, not a
connector.

## Acquisition checklist — what to get from the websites
- [ ] **Crawl4AI** — nothing to buy; `pip install crawl4ai` (self-hosted in the worker). May want a Playwright browser install in the Docker image.
- [ ] **Browser agent** — pick the lib (`browser-use` is the leading LLM-driven one); needs a headless browser in the image + (admin/demo) the founder's own session cookies for the target platforms. No paid key.
- [ ] **Apify** — already have token. For LinkedIn/IG/Maps actors, confirm which actors + that the free/PAYG credit covers expected volume; may need residential-proxy add-on for IG at scale.
- [ ] **CodeRabbit** — sign in at coderabbit.ai with GitHub, install the app on the `aresis` repo. Free for public repos. (No key in `.env`.)
- [ ] **PostHog** (later) — create a project at posthog.com (EU cloud for GDPR), get the project API key → `ARESCOPE_POSTHOG_KEY` when we wire it.
- [ ] **Burp Suite** — download Community edition (local desktop, no account needed) for the hardening pass.
- [ ] **Firecrawl** — only if Crawl4AI stalls: firecrawl.dev API key → `ARESCOPE_FIRECRAWL_API_KEY` (drop-in).
- [ ] **IntelX** — key already in `.env` (`ARESCOPE_INTELX_API_KEY`); connector not built yet.
- [ ] Headroom / Emergent / Openscreen / LLM-council / Remotion / Anime.js — nothing to acquire (skipped or pull-per-need).
