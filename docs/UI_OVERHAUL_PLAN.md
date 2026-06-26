# Arescope UI overhaul — parallel-agent work plan

**Audience:** multiple coding agents (Codex hackathon, ~2 days) working **simultaneously**.
**Goal:** ship the dashboard + identity-map UI changes below without stepping on each other.
**Author's note:** written 2026-06-26 after the map-overhaul PR (#6, merged to `main`). No code
written here — this is the brief. Each agent: read your workstream + the two "global" sections
(Conventions, Shared contracts), branch, implement, open a PR, let CodeRabbit review, merge.

---

## 0. Conventions every agent must follow

- **Workflow:** branch off `main` → commit → push → open PR → CodeRabbit auto-reviews → address
  its findings → merge. **Never push to `main` directly.** One branch per workstream.
- **Stack:** FastAPI + Jinja templates (`arescope/web/templates/`), one global stylesheet
  (`arescope/web/static/app.css`), vanilla JS inline in templates. The map uses **Cytoscape +
  fcose** (`arescope/web/static/vendor/`). The marketing/landing site is a **separate Astro app**
  in `web/` (built to `web/dist`, mounted read-only).
- **Run/deploy:** code is **baked into a Docker image** (not mounted). To see changes live:
  `docker compose build api celery_worker && docker compose up -d api celery_worker`. The app is
  at `arescope.<domain>` behind the shared nginx; locally the api binds `172.18.0.1:8000`.
  - Fast iteration without a full rebuild: copy the package into the running container and run
    with `PYTHONPATH` overlay (see how the map-overhaul session verified fixes) — but **template
    edits** are picked up only on rebuild (Jinja templates are read from the image).
- **Tests + lint:** `.venv/bin/python -m pytest -q` and `.venv/bin/ruff check arescope/ tests/`
  must pass before every PR. Add tests for new backend logic.
- **CSRF:** all POST forms include `<input type="hidden" name="csrf" value="{{ csrf }}">`; JS reads
  `window.ARESCOPE_CSRF`. New mutating endpoints must call `_check_csrf` (routes.py:149).
- **Auth guard:** authed routes start with `user = _require_verified(request)` then
  `if isinstance(user, RedirectResponse): return user` (routes.py:320,333).
- **Design bar:** dark theme, restrained. There's an Impeccable design skill + `emil-design-eng`
  skill available — invoke them for visual work. Keep typography/spacing/contrast intentional.

## 1. File-ownership matrix (read this to avoid merge conflicts)

| File | Primary owner | Others may… |
|---|---|---|
| `arescope/web/templates/map.html` | **WS-A (Map screen)** | nobody else edits |
| `arescope/web/templates/app_home.html` | **WS-B (Dashboard)** | nobody else edits |
| `arescope/web/templates/base.html` | **WS-C (Shell/Account)** | nobody else edits |
| new `arescope/web/templates/account.html` | **WS-C** | — |
| `arescope/web/routes.py` | **shared, additive only** | each WS adds its OWN new route fn; don't refactor shared helpers |
| `arescope/graph.py` | **WS-D (Backend/map-data)** | WS-A reads node shape only |
| `arescope/web/static/app.css` | **shared, additive only** | append a clearly-commented block per WS; don't rewrite existing selectors |
| `arescope/connectors/*` | **WS-E (Connectors)** | — |
| `web/src/**` (Astro landing) | **WS-F (Landing)** | — |

`app.css` and `routes.py` are the two shared hubs. Rule: **append new code in your own commented
section, never reflow existing blocks.** Conflicts then reduce to trivial end-of-file merges.

## 2. Shared API contracts (so frontend + backend agents work in parallel)

WS-D/WS-C implement these; WS-A/WS-B code against the signatures immediately.

- **Delete a scan/analysis** — `POST /app/scans/{scan_id}/delete` (CSRF). Owner-scoped. Cascades:
  `Scan → Signals + Findings` already cascade via the model (`models.Scan.signals/findings`
  `cascade="all, delete-orphan"`); delete the Scan row. Returns `{ "ok": true }` for JS, or 303 to
  `/app` for no-JS. (Replaces the "hide from map" action — see item 13.)
- **Dashboard scan rows** — `app_home` (routes.py:331) must add per row: `input_count` (int) and
  `inputs` (list of `{type, value}` — value masked for display, e.g. email→`a•••@x`) by joining
  `Subject.identifiers`. Used by item 18. Also accept `?all=1` to return every row (item 14).
- **Account page** — `GET /app/account` renders `account.html`; `POST /app/account/delete` (CSRF,
  + typed confirmation) deletes the `User` and all owned `Subjects`/`Scans` (cascade), then logs
  out. WS-C owns both.
- **Node URLs in the graph** — WS-D ensures every linkable node in `build_map_graph`
  (`graph.py`) carries `data.url`. WS-A's click handler opens `node.data.url`. (Most already do:
  `site`, `mention`, `broker` (opt_out), `photo`; verify `repo`, `inference`, LinkedIn.)

---

## WS-A — Map screen (owns `map.html` + appended map CSS)

Covers items 1, 2, 5, 6, 7, 9. This is the largest workstream; consider one strong agent.
Key file: `arescope/web/templates/map.html` (HTML overlays at top + a long inline `<script>` with
the Cytoscape setup, the `style:` array, `computeSeeds()`, `relayout()`, `relayoutIncremental()`,
`scheduleRelayout()`, the hover/trace handlers, and the streaming `poll()`).

### A1 — Incremental re-layout during streaming (item 1)
- **Current:** `relayoutIncremental()` exists (map.html, added in PR#6): on each streamed batch
  (`scheduleRelayout`, 900ms debounce) it pins **every** already-settled node at its current
  position and only lays out new nodes; a full `relayout()` (re-seed all) runs once at the end.
- **Problem reported:** "no rearranging during streaming, only once at the end." Pinning *all*
  settled nodes makes new nodes squeeze into gaps with no visible local reflow.
- **Desired:** after **every** addition the **local neighbourhood** of the new node(s) reflows
  (the relevant arm/cluster relaxes), while unrelated parts (e.g. the email arm when the name arm
  grows) stay put.
- **Where/how:** in `relayoutIncremental()`, instead of pinning *all* settled nodes, pin only nodes
  **outside the affected neighbourhood** — e.g. unpin the new nodes **and their immediate
  connected component / same-input arm**, pin the rest. fcose then relaxes just that cluster. Verify
  `scheduleRelayout` actually fires mid-stream (log it); confirm the debounce isn't swallowed.
- **Acceptance:** watching a live build, each batch visibly settles its own cluster; other arms
  don't jump.

### A2 — Clickable node links (item 2)
- **Current:** clicking a node only focuses it for Opus (scan scope) or nothing. Node data already
  carries `url` for `site`/`mention`/`broker`/`photo`.
- **Desired:** clicking a node with a `url` opens it in a new tab (web pages, Instagram, LinkedIn,
  repos, broker opt-out, contributor pages). Keep the hover-trace behaviour; add an obvious
  affordance (cursor pointer + a small ↗ on the tooltip).
- **Where:** the `cy.on('tap'/'click', 'node', …)` area; `decorate()` already maps url→imgUrl for
  photos. Coordinate with **WS-D** to guarantee `data.url` on all linkable node types.
- **Gotcha:** open via `window.open(url, '_blank', 'noopener')`; never the user's own input nodes.

### A3 — Icon **is** the node (item 5)
- **Current:** site/mention/broker nodes are a **white disc with the logo inset at ~60%**
  (`style:` block: `node[type="site"]` etc. set `background-color:#fff` + `background-width:62%`).
  Zoomed out, everything reads as white circles.
- **Desired:** the platform icon **fills** the node, **cropped to a circle** (e.g. GitHub mark IS
  the node, edge-to-edge), so platforms are recognisable when zoomed out. Photo nodes already do
  this (`node[type="photo"]` uses `background-fit:cover`).
- **Where:** the Cytoscape `style:` array. Use `background-fit: cover` / full `background-width`,
  `shape: ellipse`, a thin severity ring. Logos come from `/app/logo/<slug>` (Simple Icons, with a
  monogram fallback — many brand SVGs are monochrome on transparent, so add a tinted disc *behind*
  for contrast, or request the coloured Simple Icons variant). Keep the monogram fallback legible.
- **Acceptance:** at ~40% zoom you can tell GitHub from Instagram from a broker at a glance.

### A4 — Collapse the control bar into a menu (items 6, 7, 9)
- **Current top-left overlay** (`.map-tl`, map.html:11-29): a back link + title + a `.map-controls`
  row of buttons: **Fit**, **Re-layout**, **+ Add to identity**, **↻ Rerun**, **Sources**,
  **✦ What can be inferred?**, and the node/edge count. There are right-side slide-in panels:
  `#mapReport` (inference) and `#mapSources` (Sources). `base.html` renders a global top appbar too.
- **Desired:**
  - **Top-left:** a single primary button **"Analyze"** (rename of "✦ What can be inferred?", keep
    it green/primary, keep its `#evaluateBtn` behaviour → opens `#mapReport`). The **"Arescope"**
    wordmark (currently `base.html` `.brand`, links to `/`) becomes a button to the **dashboard**
    (`/app`) — see WS-C for the global change; on the map, ensure it's reachable top-left.
  - Below "Analyze": a small **"Maps"** button that opens a **left** panel listing the user's maps
    (so you can hop between them). Data: reuse the dashboard scans query filtered to `mode=='map'`
    (add a small `GET /app/maps/list` JSON endpoint, or render server-side into the template).
  - **Top-right:** a **hamburger (≡)** button. Clicking it slides in a **right panel** containing
    the moved controls: Fit, Re-layout, + Add to identity, ↻ Rerun. Clicking again hides it.
  - **Remove the "Sources" button/tab** entirely (and its `#mapSources` panel + `#sourcesBtn`
    handler) — the user doesn't want it.
- **Where:** `.map-tl`/`.map-controls` markup + the inline JS that wires `#cyFit`, `#cyRelayout`,
  `#addIdentity`, `#sourcesBtn`, `#evaluateBtn`; append panel CSS to `app.css`. The `#addPanel`
  (Add-to-identity form) and `#mapReport` already exist — reuse the slide-in panel pattern.
- **Gotcha:** keep keyboard focus management + the existing `reportClose` close button. Don't break
  the streaming `#mapBuilding` indicator or the `.map-legend`/`.map-hint`.
- **Acceptance:** map screen shows only "Analyze" (+ Arescope→dashboard, + Maps) on the left and a
  ≡ on the right; all other controls live behind the ≡ panel; Sources is gone.

---

## WS-B — Dashboard (owns `app_home.html` + appended dashboard CSS)

Covers items 10, 11, 12, 13 (frontend), 14, 18 (dashboard label). Key file:
`arescope/web/templates/app_home.html`. Backend bits (`app_home` route data, delete route) are in
the **Shared contracts** — code against them; WS-D/WS-C land the server side.

### B1 — Hide identity maps from the analyses list (item 10)
- **Current:** the "Recent analyses" `<ul class="scan-list">` lists **all** scans incl. `mode=='map'`
  (shows a `map` chip). The "Build identity map" button stays (header, line 13).
- **Desired:** the list shows **only analyses** (`mode != 'map'`). Keep the button. (Maps are now
  reachable from the map screen's "Maps" panel — WS-A.)
- **Where:** the `{% for sc in scans %}` loop (filter in template or have WS-D's route exclude maps).

### B2 — Fixate the "completed" chip position (item 11)
- **Current:** `.scan-row` is a flex row `scan-name | scan-chips | scan-date`; the status chip
  drifts because `scan-name` width varies → "a few millimetres off."
- **Desired:** status chip sits in a **fixed column**, pixel-stable across rows.
- **Where:** `app.css` `.scan-row`/`.scan-chips` — convert to `display:grid` with fixed
  `grid-template-columns` (e.g. `1fr auto auto`) so the status column is positionally stable.

### B3 — Drop the "off map" chip (item 12) + swap "Hide from map" → "Delete" (item 13)
- **Current:** each row shows an `off map` chip (`.js-offmap`) and the row-menu (`.row-pop`) has
  **Rename** + a **Hide/Show from map** form (`form.js-mapvis` → `/app/scans/{id}/map-visibility`).
- **Desired:** remove the `off map` chip entirely. In the row-menu, **remove the map-visibility
  action and add "Delete"** → `POST /app/scans/{id}/delete` (Shared contract). Confirm before
  deleting (small inline confirm, like the rename two-step). On success remove the `<li>` from the
  DOM (mirror the existing AJAX pattern in the `<script>` at the bottom).
- **Where:** the `.scan-chips` markup, the `.row-pop` actions, and the inline `<script>` (replace
  the `form.js-mapvis` handler with a delete handler). You can delete the now-unused
  `/app/scans/{id}/map-visibility` route + its JS once nothing references it (coordinate with WS-D).

### B4 — Show recent 3–5 + "Show all" (item 14)
- **Current:** the loop renders **every** scan.
- **Desired:** render the most recent **5** by default; a **"Show all"** control reveals the rest
  (server `?all=1` re-render, or render all hidden and toggle with JS — JS toggle is simplest and
  avoids a round-trip). Keep the stat-grid counts accurate (use total count, not the capped list).

### B5 — Better analysis labels (item 18)
- **Current:** label = `sc.name or ('Map '/'Analysis ') ~ sc.id[:8]` → "Analysis 1a2b3c4d".
- **Desired:** when **unnamed**, label by **input count** (e.g. "3 inputs") with a small **ⓘ** icon
  that reveals exactly which inputs were given (masked PII). When the user **names** it, the name
  replaces the count label. Apply the same to the **individual analysis header** in
  `results.html:12-13` ("scan {{ scan.id[:8] }}" → the input summary / name).
- **Where:** `app_home.html` `.scan-name` + a new info popover; uses `input_count`/`inputs` from the
  Shared-contract dashboard data. `results.html` needs the same data passed to its route.
- **Gotcha:** inputs are PII — mask in display (reuse `graph._mask` logic or a small server helper);
  never dump raw emails/phones into the DOM for a list view.

---

## WS-C — App shell + Account (owns `base.html` + new `account.html`; adds routes)

Covers items 8, 15, 16. Key files: `arescope/web/templates/base.html` (global appbar), a new
`account.html`, and new routes in `routes.py` (additive).

### C1 — "Arescope" → dashboard (item 8)
- **Current:** `base.html:13` `<a class="brand" href="/">ARESCOPE</a>` → landing page.
- **Desired:** when logged in, the brand links to the **dashboard** `/app` (logged-out keeps `/`).

### C2 — Remove the "username · admin" text (item 15)
- **Current:** `base.html:20` `<span class="who">{{ user.username }}{% if user.is_admin %} · admin
  {% endif %}</span>` → renders "admin · admin" for the admin user, wedged between the Admin link
  and Log out.
- **Desired:** delete that `<span class="who">`.

### C3 — Profile icon → Account settings (item 16)
- **Current:** no account/settings page exists (routes are signup/login/logout/magic/verify/admin).
- **Desired:** add a **profile icon button** *below* the Log-out control (the user was explicit:
  **not** in the top bar — a stacked icon under Log out) that links to **`/app/account`**.
  - Build `account.html`: show common account info (username, email, verification status, admin
    flag, member-since) + space for "whatever this site also needs" (password change link to the
    existing `/app/password` flow, email, etc.), and a **Delete account** action (typed-confirm) →
    `POST /app/account/delete` (cascade-deletes the user's Subjects/Scans/Signals/Findings, then
    logs out and redirects to `/`).
  - Routes (additive in `routes.py`): `GET /app/account` (render) + `POST /app/account/delete`
    (CSRF + confirmation). Follow the `_require_verified` guard pattern.
- **Gotcha:** account deletion is destructive + irreversible — require typing the username/email to
  confirm, and double-check the cascade actually removes everything owned (Subjects → Scans →
  Signals/Findings/Remediations; ChatMessages keyed by `user_id`).

---

## WS-D — Backend / map-data (owns `graph.py`; additive routes; coordinates contracts)

Covers the server side of items 2, 10, 13, 14, 18 + investigates item 3's rendering. Land the
**Shared contracts** early so WS-A/B/C can integrate.

- **D1 (item 2 data):** in `build_map_graph` (`graph.py`), ensure every linkable node carries
  `data.url`. Audit `_classify`/`build_map_graph`: `repo` nodes (GitHub repo url), `inference`
  (none — leave), LinkedIn account nodes (the profile url). Web/mention/site/broker already have it.
- **D2 (items 10/14/18 data):** extend `app_home` (routes.py:331) — add `input_count` + masked
  `inputs` per scan (join `Subject.identifiers`), support `?all=1`, and either exclude `mode=='map'`
  or let WS-B filter. Pass the same input summary to the analysis view route for `results.html`.
- **D3 (item 13):** implement `POST /app/scans/{id}/delete` (owner-scoped, CSRF). Remove the old
  `/app/scans/{id}/map-visibility` route once WS-B drops its UI.
- **D4 (item 3 — LinkedIn node, investigate):** PR#6 made `_enrich_linkedin` (`service.py`) harvest
  the LinkedIn URL from `web_mention` signals (Tavily/Brave), so a `linkedin_jina` **account**
  signal should now produce a `site:linkedin.com` node carrying headline/bio in `raw.description`.
  **Why the user saw no LinkedIn node:** their map predates the fix. Verify on a fresh run; check
  worker logs for a `linkedin_jina` gap (Jina rate-limit/block). Then **deepen** the node: surface
  the headline/bio/location/company on the node tooltip + as the node label, and (admin) wire the
  Apify LinkedIn actor for the richer profile (`linkedin.fetch_via_apify`). Coordinate node shape
  with WS-A.

## WS-E — Connectors: messaging-app profile pictures (item 4)

**Read this before coding — most of item 4 is not publicly feasible; don't burn hours.**
- **Why WhatsApp doesn't show up from the phone number today:** there is **no public API** that
  returns a WhatsApp profile photo from a phone number. WhatsApp only shows a contact's photo to
  people who have them saved *and* whom the user allows; `wa.me/<number>` confirms an account exists
  but exposes **no photo**. The existing `ignorant` connector (`phone_tools.py`) already does the
  "is this number registered on site X" check — that's the realistic ceiling for WhatsApp/Signal.
- **Signal:** no public lookup at all (privacy by design). Out of scope.
- **Telegram:** photos are public **only for public usernames** (`t.me/<username>`), and you can't
  reliably go phone→username without the contact being in an address book. If we already have a
  **username** input, a Telegram public-profile check (`t.me/<username>`, scrape the og:image) is
  feasible — model it as a **username** connector, not a phone one. Camoufox (`browser.py`,
  installed in PR#6) can render `t.me/<username>` and read the profile photo.
- **Recommended scope for this WS:** (a) add a Telegram **username**→public-profile-photo connector
  via Camoufox (emit a `photo` `identity_attribute`, same shape as Instagram/GHunt so it rides the
  existing photo-node rendering); (b) for WhatsApp, at most a phone→"has WhatsApp" existence signal
  (no photo) — and **honestly label it** (CLAUDE.md: never imply coverage we don't have). Document
  the Signal/WhatsApp-photo impossibility in `docs/EXTENDED_SEARCH_SCOPE.md`.
- **Files:** new connector in `arescope/connectors/`, register in `connectors/registry.py`, reuse
  `browser.render()`/`fetch()` and `_identity.identity_signal(..., attribute=PHOTO)`.

## WS-F — Landing page: Impressum (item 17)

- **Where:** the landing page is the Astro app `web/src/pages/index.astro` (+ components in
  `web/src/components/`), built with `npm run build` in `web/` → `web/dist` (mounted into the api).
- **Desired:** an **Impressum** (German legal-notice) reachable from the landing footer (a small
  link/button at the bottom). Likely a new `web/src/pages/impressum.astro` + a footer link.
- **⚠️ Needs user input — the agent MUST ask Patrik before drafting.** Known so far: operator is
  **Patrik Breeck**, contact **pab@patrikbreeck.de**. A German Impressum (TMG §5) typically also
  needs: full **postal address**, whether it's a private individual vs. a registered business
  (and if business: legal form, register court + number, VAT ID), a **responsible person** for
  content (§55 RStV) if there's editorial content, and a phone or contact form. **Ask Patrik for:
  postal address, business-or-individual status, any VAT/registration numbers, and a preferred
  contact method** before writing the Impressum. Don't invent legal details.

---

## Suggested parallel assignment (6 agents, minimal overlap)

| Agent | Branch | Scope | Touches |
|---|---|---|---|
| 1 | `ui/map-screen` | WS-A (items 1,2,5,6,7,9) | `map.html`, app.css (map block) |
| 2 | `ui/dashboard` | WS-B (items 10,11,12,13,14,18) | `app_home.html`, app.css (dash block) |
| 3 | `ui/shell-account` | WS-C (items 8,15,16) | `base.html`, `account.html`, routes (account) |
| 4 | `be/map-data` | WS-D (items 2,3,10,13,14,18 backend) | `graph.py`, `service.py`, routes (additive) |
| 5 | `feat/messaging-photos` | WS-E (item 4) | `connectors/*`, registry, docs |
| 6 | `web/impressum` | WS-F (item 17) | `web/src/**` (Astro) |

**Sequencing tip:** Agent 4 (backend contracts) should land `POST /app/scans/{id}/delete`, the
account routes' stubs, and the dashboard `input_count`/`inputs` data **first** (small, fast), so
Agents 2/3 can integrate without blocking. Agents 1, 5, 6 are fully independent and can start
immediately. The only shared files are `routes.py` and `app.css` — keep edits **additive and in
clearly-commented per-agent sections** and merges stay trivial.

## Open questions for Patrik (resolve before/early in the session)

1. **Impressum (WS-F):** postal address, individual vs. business, VAT/registration numbers,
   preferred contact. (Agent 6 will ask.)
2. **Map vs. global appbar (WS-A/C):** on the map screen, should the global `base.html` appbar be
   hidden in favour of the map's own top-left/right controls, or kept above it? The plan assumes the
   map controls are the primary surface there; confirm the intended relationship.
3. **Telegram/WhatsApp (WS-E):** OK to ship WhatsApp as existence-only (no photo) and Telegram as
   username-only? (That's the honest feasible scope.)
