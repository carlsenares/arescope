"""Celery tasks: run scans async + prune expired scans (retention TTL)."""

from __future__ import annotations

from datetime import datetime, timezone

from arescope.db import models
from arescope.db.session import session_scope
from arescope.service import run_and_store_scan
from arescope.worker.celery_app import celery_app


@celery_app.task(name="arescope.run_scan")
def run_scan_task(subject_id: str) -> str:
    return run_and_store_scan(subject_id)


@celery_app.task(name="arescope.prune_expired")
def prune_expired_task() -> int:
    """Delete scans past their retention TTL (ARCHITECTURE.md §4.4)."""
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        expired = s.query(models.Scan).filter(models.Scan.expires_at < now).all()
        count = len(expired)
        for scan in expired:
            s.delete(scan)  # cascades to signals/findings/remediations
    return count
