"""FastAPI surface — thin (ARCHITECTURE.md §2): accept scans, return status + report.

The scan runs async as a Celery task; the client polls. All real logic lives in
the engine + service layer.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from aresis.db import models
from aresis.db.session import init_db, session_scope
from aresis.schemas import Identifier
from aresis.service import create_subject
from aresis.worker.tasks import run_scan_task

app = FastAPI(title="Aresis", version="0.1.0")


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
    task = run_scan_task.delay(subject_id)
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
            "findings": [
                {
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
                }
                for f in findings
            ],
        }


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}
