# Arescope — Exposure Map (graph visualization)

> Status: **design** (not built). This is the clear picture + implementation plan
> for the interactive "mapping" of a user's exposure. Read alongside
> `AI_PIPELINE.md` (where the data comes from) and `ARCHITECTURE.md` (data model).

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

## 9. Open questions
- Masking depth in labels (how much of an email to show before hover).
- Whether per-account aggregation needs its own cache (rebuild on each scan complete).
- Post-level scraping is a **new collection capability** and re-opens the ownership
  question (only the user's own posts) — gate before building §8.4.
