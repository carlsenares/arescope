# Arescope — Status & Next Session

> Living handoff. Last updated 2026-06-22. The source of truth for "where are we
> and what's next." Pair with `ROADMAP.md` (phases), `AI_PIPELINE.md` (engine),
> `GRAPH.md` (map), `OWNERSHIP_VERIFICATION.md` (the P2 gate).

## How it's deployed (read first)
- **Live at https://arescope.com**, served by the FastAPI app (single origin: the
  app routes + the built Astro landing via catch-all). Runs on the consolidated
  server behind the shared `insureai_nginx` gateway.
- **Stack:** `docker compose` (root `docker-compose.yml` + gitignored
  `docker-compose.override.yml`): `api`, `celery_worker`, `postgres`, `redis`, all
  `restart: unless-stopped`. Override notes: postgres host port unpublished (avoids
  clashing with the box's other Postgres on :5432); api bound to `172.18.0.1:8000`
  only (nginx proxies there); `web/dist` bind-mounted into the api so it serves the
  landing; image installs `.[connectors]` (Holehe/Maigret + trio).
- **nginx:** `/root/insureai/InsureAI/backend/nginx/conf.d/arescope.conf` proxies
  arescope.com → `172.18.0.1:8000`. Backed up before edits; `nginx -t` before reload.
- **⚠️ Deploy gotcha:** templates / CSS / Python are **baked into the api image**
  (`pip install .`). After changing them you MUST
  `docker compose up -d --build api` — a plain restart won't pick them up.
  (`web/dist` and is the only bind-mount, so landing-only changes just need
  `npm run build`.)
- **Migrations:** no Alembic yet. `python -m arescope.manage migrate` (idempotent,
  `ADD COLUMN IF NOT EXISTS`) after model changes; run it in the api container on
  prod. Columns added so far: `users.can_scan`, `scans.options`, `scans.name`.
- **Keys (.env, gitignored):** Anthropic, HIBP (core), Shodan (academic "dev"),
  Resend (live, arescope.com verified), Fernet, session secret, `COOKIE_SECURE=true`,
  `BASE_URL=https://arescope.com`. Admin account: `pab@patrikbreeck.de` (username
  `admin`, is_admin + verified). Sign in via magic link.

## Built & live
- **Auth:** username/email + password, **magic-link** (passwordless login + signup
  email verification), cross-device verify polling. **Email-verification gate**:
  unverified non-admins are bounced to `/verify-email` before any app surface.
- **Run-lock:** `User.can_scan` (default off; admins always allowed). **Admin
  dashboard** `/app/admin` grants/revokes per user in real time. This is the paywall
  seam. Admins also **bypass the self-audit ownership confirmation** on a scan.
- **Input form:** one identifier per field (email/username/name/ip), optional
  **analysis name**, and a **Maigret choice** (Full ~4 min vs Top-50 ~30s) shown
  when a username is entered.
- **Connectors (all 5 live & verified):** HIBP, Hudson Rock, Holehe, Maigret,
  Shodan. (Holehe/Maigret were silently absent from the image until the
  `.[connectors]` fix — see git history.)
- **Engine:** clustering → Haiku triage → Opus per-cluster judge → on-demand
  per-finding remediation + deterministic question resolution (`AI_PIPELINE.md`).
- **Results UI** `/app/scans/{id}`: findings as independent cards (severity, Opus
  rationale, inline easy fix, per-finding **Generate solution**, inline yes/no
  **question answering** that re-rates). **Streams** — each finding persists the
  moment Opus judges it; fast sources first, Maigret as a 2nd wave with a progress
  phase; the page polls and renders findings as they land.
- **Exposure Map** `/app/map` (whole account) + `/app/scans/{id}/map`: Cytoscape.js
  node-link map, content-addressed/deduped (same platform across inputs = one node),
  severity-coloured, hover cards, self-hosted cached logos. See `GRAPH.md`.
- **Security:** removed the unauthenticated `/scans` + `/findings` JSON endpoints;
  everything is session-authed + ownership-checked.

## Next steps (prioritized)
1. **Map layout stability** — persist node positions and only ease *new* nodes in,
   so an expanding account map never re-jumbles. The natural follow-up; `GRAPH.md §9`.
2. **Drive a breached input end-to-end** — the test email is genuinely clean, so the
   *Generate solution* and *Depends → questions* paths haven't been exercised against
   a real finding that needs them. Validate with a known-breached test account.
3. **Map filters + NL summary** — filter by severity/input/source; optional one-line
   LLM read of the map ("your email is the weak point"). Rendering stays Cytoscape.
4. **P2 per-input ownership gate** — still designed, not built
   (`OWNERSHIP_VERIFICATION.md`): a user can currently scan an owned email ≠ their
   signup email with no proof. Email=magic-link seed, username=OAuth, ip=source-match.
   Admins already bypass. Its own session.
5. **Per-post / content nodes for the map** — needs a new per-site content connector,
   which re-opens the ownership question (only the user's own posts). Gate first.
6. **Payments (Phase 2)** — Stripe; gate run count, not solutions; the `can_scan`
   seam is where it plugs in. See `DISTRIBUTION.md`.
7. **Website redesign** — the marketing landing is separate (Astro); deferred.
8. **Maigret perf** — full username scan ~4 min (top-50 mitigates). Consider a
   smarter default / progress within the wave.
9. **Graph-DB escalation** (only if the identity graph becomes core) — back the map
   projection with Neo4j/Memgraph; frontend unchanged. `GRAPH.md §9`.

## Gotchas / facts worth keeping
- Rebuild the api image for any template/CSS/py change (above).
- `Signal` DB rows don't store the subject; the map/links derive the input from the
  owning `Finding`'s `subject_type`/`subject_value` (encrypted).
- Tests are DB-free by convention (pure logic). 36 green; repo lint-clean.
- There are a few orphan/test scans in prod from verification (harmless; expire via
  retention TTL; deleting needs explicit user OK).
