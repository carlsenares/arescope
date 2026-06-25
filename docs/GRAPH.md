# Arescope — Exposure Map (graph visualization)

> Status: **design** (not built). This is the clear picture + implementation plan
> for the interactive "mapping" of a user's exposure. Read alongside
> `AI_PIPELINE.md` (where the data comes from) and `ARCHITECTURE.md` (data model).

## 0. North star (the point of the whole map) — locked 2026-06-25

> **"This is how much I can find out about you without any hard-to-get information."**

The user types only **easy public seeds** (email, phone, name, username, maybe a
photo) and is meant to be *shocked* at how much the open internet infers about them
"just by knowing where to look." Design consequences (do not relitigate):

- **No user uploads / data-export files in the map.** A "check what Instagram's
  export knows about you" feature is a *different, more boring* product — parked as
  its own future thing, explicitly NOT this map.
- The payoff is **public content that supports inference**, not "you have an account
  here": Instagram posts, LinkedIn employment/history, Google Maps reviews, tweets,
  public photos. Reviews in one city ⇒ home city; gym check-ins ⇒ routine; cuisine ⇒
  tastes. The Opus **Evaluate** step (§13) turns content into those inferences — that
  inference is the effect, not the node count.
- So the hard engineering is **extracting public content off walled/JS platforms**
  (IG/LinkedIn/Google) that have no clean API — see `TOOLING_EVAL.md`. Pipeline:
  seeds → discovery (PDL/Gravatar/Maigret/Sherlock/Tavily → candidate profile URLs)
  → extraction (Apify / browser-agent / GHunt / Crawl4AI → posts/reviews/employment/
  photos) → inference (Opus Evaluate). The browser agent gets the *logged-in view*
  but only scales for the founder's own check / the demo (shared creds rate-limit).

## 1. What it actually is

Not a chart — a **node-link map of the user's footprint**, centered on them, that
makes the identity graph we already compute *visible*. One glance should answer:
"what is connected to me, through which identifier, and how dangerous is it?"

The data already exists: every scan produces `Signal`s (source, kind, locator,
raw) grouped into `Finding`s (category + severity). The map is a **deterministic
projection** of those rows — there is nothing to "generate." (See §7 on why this
is *not* a job for an "AI graphing tool".)

## 2. Structure — nodes & edges

```
            ┌── breach: Adobe (2013) ──┐ (red edge: critical)
 email ─────┤                          │
            └── site: LinkedIn ◄────────┐ (same account →
 (you)──┤                               │  one node, two edges)
            ┌── site: LinkedIn ◄────────┘
 username ──┤
            ├── site: GitHub ── post: "…" (extension)
            └── site: Reddit
 ip ──────── host 203.0.113.4 ── :22 SSH ── CVE-2024-1234
```

| Node type | Source | Visual | Hover payload |
|---|---|---|---|
| **Identity** (center) | the account | larger, "you"/handle | account, # inputs, # findings |
| **Input** (the "arms") | each owned `Identifier` | icon per type (email/username/ip/name) | the value, what it surfaced |
| **Site / account** | Holehe (email), Maigret (username) | **real site logo** | platform, profile URL, which input(s) reached it |
| **Breach** | HIBP | shield icon | breach name, date, data classes leaked |
| **Infostealer** | Hudson Rock | malware icon | date, machine, captured creds count |
| **Host / service / CVE** | Shodan (ip) | server/port icons | port, product/version, CVE ids |
| **Post / content** *(extension)* | future per-site scrape | small dot under its site | snippet, URL, date |

**Edges** carry the relationship ("registered on", "leaked in", "exposes") and are
**colored by the severity of the `Finding` the signal belongs to** (critical→red,
high→orange, medium→amber, low→green, info→grey). Edge thickness ∝ severity too.

### The convergence rule (the important one)
A site node is keyed by **normalized platform** (domain/slug). If both an email and
a username resolve to the *same* platform (same account), they point at **one** site
node — two edges converging — exactly the "same account → same icon" behavior. This
is what turns a list into an identity graph: it visually fuses an identity across
inputs.

## 3. Per-analysis vs per-account

- **Per-analysis** (`/app/scans/{id}/map`): one scan's subject. Always available;
  this is what **admin** uses (admin scans arbitrary inputs, so cross-scan
  aggregation isn't meaningful for them).
- **Per-account** (`/app/map`): aggregate **all of a user's scans** into one map —
  multiple email/username arms, site nodes deduped across every input. A user who
  has scanned all their emails gets one rich map of their whole footprint. This is
  the headline view for real users.

## 4. Layout & interaction
- **Layout:** radial/concentric — identity at center, input arms in ring 1, their
  findings (sites/breaches/services) in ring 2, extensions (posts/CVEs) in ring 3.
  `fcose` (force-directed, organic) is the default; `concentric` is the explicit
  ringed alternative. Center node is pinned.
- Pan + zoom + scroll; click a node to focus/expand its subtree; hover for the
  detail card; filter chips (by severity / by input / by source).
- Severity legend; "N nodes · M connections" header. Professional dark theme that
  matches the app tokens (same OKLCH palette, logos on white chips for contrast).

## 5. Data pipeline (from our existing schema)

```
Identifier(type,value)              -> input nodes (+ center)
Signal(source,kind,locator,raw)     -> site / breach / stealer / host nodes
  raw.url        -> profile link + domain -> logo
  raw.data_classes / vulns / tags  -> hover payload
Finding(severity, signal_ids[])     -> edge color (map signal -> its finding)
```

A **graph-builder** service walks the user's `Signal`s + `Finding`s + `Identifier`s
and emits Cytoscape elements JSON:

```jsonc
{
  "nodes": [
    {"data": {"id": "self", "type": "identity", "label": "you"}},
    {"data": {"id": "in:email:0", "type": "input", "kind": "email", "label": "j…@gmail.com"}},
    {"data": {"id": "site:linkedin.com", "type": "site", "label": "LinkedIn",
              "logo": "https://…/linkedin.svg", "url": "https://linkedin.com/in/…"}}
  ],
  "edges": [
    {"data": {"id": "e1", "source": "in:email:0", "target": "site:linkedin.com",
              "severity": "high", "finding_id": "…", "label": "registered"}}
  ]
}
```

Served from an **auth'd, ownership-checked** route (same guard as the results page).
PII stays the user's own (self-audit); values are masked in labels, full detail only
in hover.

## 6. Tooling decision

**Use [Cytoscape.js](https://js.cytoscape.org/).** It's the best fit for *this* stack:
- Framework-agnostic plain JS — drops into our server-rendered Jinja app via a
  `<script>` + a JSON endpoint (no React build needed).
- First-class **node background images** (real logos), rich stylesheet (color/size
  by data), hover/click events, and built-in layouts (`fcose`, `concentric`) +
  graph algorithms if we want "shortest path from you to your worst exposure."
- Mature, used in bioinformatics/network analysis; our graphs are hundreds of nodes,
  well within its canvas renderer.

Alternatives and when they'd win:
- **[Sigma.js](https://www.sigmajs.org/)** (WebGL, graphology) — only if account maps
  ever reach 10k–100k nodes. Same data layer, swap later; more work for logos.
- **react-force-graph** — great, but it's React; we'd adopt it only if the app moves
  to React/islands.
- vis-network / G6 / yFiles(paid) — fine, but no advantage here over Cytoscape.

**Logos:** map known platforms → [Simple Icons](https://simpleicons.org) SVG slugs
(crisp, brand-correct); fall back to a favicon service
(`google.com/s2/favicons?domain=…&sz=64`) for the long tail. Resolve the domain in
the backend from `signal.raw.url`.

## 7. On "AI graphing tool"
The map is a **deterministic projection of structured data we already have** — an
LLM is the wrong tool to *render* it (and would add latency, cost, and
nondeterminism). Where AI legitimately helps, later: a one-line **natural-language
summary** of the map ("your email is the weak point — 3 of 4 criticals trace to it"),
or auto-suggesting **groupings/clusters**. Rendering + layout = Cytoscape.js.

## 8. Implementation phases
1. **Builder + endpoint** — `graph.py` service: `build_graph(user)` /
   `build_graph_for_scan(scan_id)` → Cytoscape JSON. Auth'd routes `/app/map` and
   `/app/scans/{id}/map`. Platform-normalization + logo resolution. (Backend only,
   unit-testable.)
2. **Map page** — vendored Cytoscape.js + `fcose`, the stylesheet (severity colors,
   logo chips, sizing), pan/zoom, hover detail card, legend. Link from dashboard +
   results.
3. **Polish** — filters (severity/input/source), focus-on-click expand, the radial
   layout tuning, empty/partial states (graph fills in as the scan streams).
4. **Extensions** — post/content nodes (needs a per-site content connector), CVE
   sub-nodes for Shodan, cross-edges ("reused password across these breaches"),
   the NL summary.

## 9. Dynamic by design (not hardcoded)
The node/edge *taxonomy* is a fixed, legible schema; the *graph* is fully
data-driven and rebuilt on every view, so it adapts as analyses accumulate:
- **Content-addressed ids** (`site:<domain>`, `breach:<name>`) mean the same
  platform reached by many inputs — even across separate scans — collapses to ONE
  node with many edges. Add 10 more email scans and they merge in with zero
  overlap; shared platforms are shared nodes automatically (proven: 2 inputs →
  24 deduped site nodes in the first live account map).
- **Severity flows from the finding**, so a node inherits the worst severity
  touching it as new evidence lands.
- **Force layout** (`cose`) computes positions each render — no fixed
  coordinates. Next step for stability: persist positions and only ease *new*
  nodes in, so an expanding map never re-jumbles.
- **Upgrade path:** for hundreds of nodes/account, projecting from Postgres is
  correct. If the identity graph becomes the core product (it's the moat —
  see POSITIONING.md), back the projection with a **graph database**
  (Neo4j/Memgraph) — the Cytoscape frontend doesn't change. This is also where an
  "AI" layer could add a natural-language read of the map, never the rendering.

## 10. Open questions
- Masking depth in labels (how much of an email to show before hover).
- Whether per-account aggregation needs its own cache (rebuild on each scan complete).
- Post-level scraping is a **new collection capability** and re-opens the ownership
  question (only the user's own posts) — gate before building §8.4.

## 11. Shipped 2026-06-23 — full-wall canvas + profile photos
- **Full-wall map.** The canvas now breaks out of the centred 920px column *and*
  cancels the `appmain` padding (`mapwrap`: `100vw × calc(100vh - 64px)`), so the
  graph owns the whole viewport below the 64px appbar. Title, view controls, node
  count and the severity legend float as frosted-glass overlays (top-left +
  bottom-left) instead of stacking above the canvas. (`map.html`, `app.css`.)
- **Real profile photos, default-aware.** Connectors now carry a photo's
  `is_default` flag (`identity_signal(meta=…)`); GHunt reads Google's structured
  `{url, isDefault}` (`_profile_photo`) to tell a real uploaded face from the
  letter-monogram default. A **real** image becomes a map node rendered with the
  face as its fill and shows in the finding card; a **default** avatar stays a
  plain node / a "no real picture is public" note. The judge prompt rates
  `is_default=true` info/low and a real face medium+.
- **Image proxy** `/app/photo?u=` — auth-gated, host-allow-listed
  (lh3.googleusercontent.com / avatars.githubusercontent.com / gravatar.com),
  cached by URL hash. The browser never hotlinks Google/Gravatar (no third-party
  leak, no open proxy / SSRF). Mirrors the existing `/app/logo` proxy.

## 12. Planned restructuring (agreed 2026-06-23, not yet built)
Direction set with the user; **deferred** behind the master-plan "max collection
power first" directive (see [aresis-build-strategy] memory + MASTER_PLAN.md). These
are presentation-layer reshapes — they do not touch the collection engine, so
building collection depth now costs nothing when we re-surface later.

1. **Decouple the graph into its own product surface: "Online Identity Mapping."**
   The privacy audit keeps answering *"what's wrong / how do I fix it"* (findings as
   they are now). A separate Mapping function answers *"what's connected / what's my
   reach."* The audit may still build a graph, but Mapping is the dedicated map.
   - **Real-time / streaming map.** Build the live map from **Signals (pre-judge)**,
     not Findings (post-judge), so nodes pop in the instant a connector returns and
     severity colour fills in as the judge catches up. The wave-based
     `run_and_store_scan` + per-cluster persist already gives us the streaming spine;
     add an SSE/websocket delta feed of node/edge additions.
   - Mapping input = **everything at once** (it's about reach, not organisation).

2. **Tabbed audit inputs by type: email / username / IP / name** — replace the one
   big multi-field form. Each tab maps 1:1 onto the per-input ownership gate
   (OWNERSHIP_VERIFICATION.md: email=magic-link, username=OAuth, ip=source-match,
   name=filter-only) and can state what it searches + its verification requirement.

3. **"Where it came from" web (the structural map change).** Today edges go
   `input → attribute` directly (`graph.py` `put_edge(in_id, node_id, …)`) and
   `name/bio/company/links` are finding-only (`graph.py` `_classify` returns None for
   them). To show reach: chain `input → site → attribute` and promote name / company /
   location / school / address to nodes hung off the **site that leaked them**
   (e.g. GitHub → real name), so the map shows the full picture of where each fact
   surfaced. Per-post / bio nodes still need a content connector (a new collection
   capability — re-opens the ownership question; gate before building, see §10).

## 13. Decision 2026-06-23 — analysis and the graph are SEPARATE surfaces
The analysis (search) graph is **removed**. There is now exactly one graph, fed only
by **map mode**. Rationale: the two answer different questions and conflating them
confused the search effort.

- **Analysis / search** = *exposure findings*: gross registries, breaches, leaks,
  infostealer, broker listings. Opus judges each finding + severity. (unchanged)
- **Graph / map (Online Identity Mapping)** = *reach + extended search*: account
  registrations, profile pictures, posts, and any information derivable from those.
  No per-finding Opus.
- Removed: `build_scan_graph` / `build_account_graph` route entry points
  (`/app/scans/{id}/map`, `/app/map` → now redirects to `/app/map/new`); the "View
  map" link on results; nav "Map" → "Identity map" (the builder). The builder funcs
  stay in graph.py for now but are unwired. `exclude_from_map` toggle is now moot.

### 13a. "Evaluate" — Opus over the graph (the map's intelligence layer, planned)
Instead of judging individual findings, map mode gets an **Evaluate** action: Opus
navigates the assembled graph and returns a verdict — is this online identity normal,
or over-exposed, and **which exact parts** drive that. This is also where
**reasonable deductions** live: e.g. all Google reviews in Cologne ⇒ infer home city;
restaurant categories ⇒ food preferences; a review edited several times ⇒ repeat
customer. Opus only runs here on demand (cost-bounded), not per node.

### 13b. Location is recorded EVERY time, separately (graph change, planned)
Today location nodes are content-addressed by value, so "Cologne" from an IP, from
photo EXIF, from a phone prefix, and from review clustering would collapse into ONE
node. **Change this:** key location (and similar derivable facts) by *(source/
endpoint, value)* so each exposure stays its own node/edge. The point is to show *how
many different endpoints leak the same fact* — that multiplicity is itself the
finding. Convergence still applies to genuine same-account nodes (sites/breaches).
