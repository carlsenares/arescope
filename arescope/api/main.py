"""FastAPI surface — thin (ARCHITECTURE.md §2).

All user-facing flows are the server-rendered, session-authenticated web app
(arescope.web.routes): signup/login, the input form, and the results view with
on-demand solutions + question resolution. We deliberately expose NO
unauthenticated JSON CRUD for scans/findings — those would leak PII and let
anyone burn LLM spend. The only bare endpoint is the health check.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from arescope.config import get_settings
from arescope.db.session import init_db
from arescope.web.routes import APP_STATIC_DIR, router as web_router

_cfg = get_settings()

app = FastAPI(title="Arescope", version="0.1.0")

# Signed session cookie (httpOnly) — carries only the user id; see arescope.auth.
app.add_middleware(
    SessionMiddleware,
    secret_key=_cfg.session_secret,
    max_age=_cfg.session_max_age,
    https_only=_cfg.cookie_secure,
    same_site="lax",
)

# Server-rendered app pages (signup / login / dashboard / new scan / results).
app.include_router(web_router)

# App assets (its own stylesheet + fonts), served under /app/static.
app.mount("/app/static", StaticFiles(directory=APP_STATIC_DIR), name="app-static")


@app.on_event("startup")
def _startup() -> None:
    init_db()  # dev convenience; production uses alembic


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


# The static marketing site (Astro build) is served LAST as a catch-all, so the
# whole thing is one origin: app routes above win, everything else falls through
# to the landing. Skipped if the site hasn't been built yet (API still runs).
_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "web", "dist")
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="site")
