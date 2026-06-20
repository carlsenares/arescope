"""FastAPI surface — thin (ARCHITECTURE.md §2): accept scans, return status + report.

The scan runs async as a Celery task; the client polls. All real logic lives in
the engine + service layer.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from arescope.config import get_settings
from arescope.db import models
from arescope.db.session import init_db, session_scope
from arescope.schemas import Identifier
from arescope.service import (
    create_scan as create_scan_record,
    create_subject,
    generate_finding_remediation,
    resolve_finding,
)
from arescope.web.routes import APP_STATIC_DIR, router as web_router
from arescope.worker.tasks import run_scan_task

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

# Server-rendered app pages (signup / login / dashboard / new scan).
app.include_router(web_router)

# App assets (its own stylesheet + fonts), served under /app/static.
app.mount("/app/static", StaticFiles(directory=APP_STATIC_DIR), name="app-static")


def _finding_dict(f: models.Finding) -> dict:
    r = f.remediation
    return {
        "id": f.id,
        "category": f.category,
        "severity": f.severity,
        "action": f.action,
        "title": f.title,
        "rationale": f.rationale,
        "confidence": f.confidence,
        "fix_difficulty": f.fix_difficulty,
        "easy_fix": f.easy_fix,
        "questions": f.questions,
        "member_locators": f.member_locators,
        "remediation": None
        if r is None
        else {
            "tier": r.tier,
            "summary": r.summary,
            "steps": r.steps,
            "artifact": r.artifact,
        },
    }


@app.on_event("startup")
def _startup() -> None:
    init_db()  # dev convenience; production uses alembic


class ScanRequest(BaseModel):
    identifiers: list[Identifier]


class ScanCreated(BaseModel):
    subject_id: str
    task_id: str


@app.post("/scans", response_model=ScanCreated)
def create_scan(req: ScanRequest) -> ScanCreated:
    if not req.identifiers:
        raise HTTPException(400, "at least one identifier required")
    # P0: operator asserts ownership of every identifier (gate is a no-op).
    subject_id = create_subject(req.identifiers)
    scan_id = create_scan_record(subject_id)
    task = run_scan_task.delay(scan_id)
    return ScanCreated(subject_id=subject_id, task_id=task.id)


@app.get("/scans/{scan_id}")
def get_scan(scan_id: str) -> dict:
    with session_scope() as s:
        scan = s.get(models.Scan, scan_id)
        if scan is None:
            raise HTTPException(404, "scan not found")
        findings = (
            s.query(models.Finding).filter(models.Finding.scan_id == scan_id).all()
        )
        return {
            "id": scan.id,
            "status": scan.status,
            "started_at": scan.started_at,
            "finished_at": scan.finished_at,
            "expires_at": scan.expires_at,
            "coverage_gaps": scan.config_snapshot.get("coverage_gaps", []),
            "findings": [_finding_dict(f) for f in findings],
        }


@app.get("/findings/{finding_id}")
def get_finding(finding_id: str) -> dict:
    with session_scope() as s:
        f = s.get(models.Finding, finding_id)
        if f is None:
            raise HTTPException(404, "finding not found")
        return _finding_dict(f)


@app.post("/findings/{finding_id}/remediation")
def create_remediation(finding_id: str) -> dict:
    """Generate the involved, tailored fix for a finding on demand (paywall point)."""
    try:
        generate_finding_remediation(finding_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return get_finding(finding_id)


class ResolveRequest(BaseModel):
    # question index -> yes(True) / no(False); unanswered questions stay contingent
    answers: dict[int, bool]


@app.post("/findings/{finding_id}/resolve")
def resolve_finding_endpoint(finding_id: str, req: ResolveRequest) -> dict:
    """Resolve a DEPENDS finding from the user's yes/no answers — free, no LLM."""
    try:
        resolve_finding(finding_id, req.answers)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return get_finding(finding_id)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


# The static marketing site (Astro build) is served LAST as a catch-all, so the
# whole thing is one origin: app routes above win, everything else falls through
# to the landing. Skipped if the site hasn't been built yet (API still runs).
_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "web", "dist")
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="site")
