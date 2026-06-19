"""Service layer: bridges the stateless engine to persistence.

Creates subjects/identifiers, runs the engine, and writes signals/findings/
remediations with a retention TTL. Kept separate from orchestrator.py so the
engine stays stateless and unit-testable.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aresis.config import get_settings
from aresis.db import models
from aresis.db.session import session_scope
from aresis.pipeline.orchestrator import run_scan
from aresis.pipeline.report import ScanReport, render_markdown
from aresis.schemas import Identifier as IdentifierSchema
from aresis.schemas import InputType


def create_subject(identifiers: list[IdentifierSchema], user_id: str | None = None) -> str:
    """Persist a subject + its (encrypted) identifiers. Returns subject_id."""
    with session_scope() as s:
        subject = models.Subject(user_id=user_id, label="self")
        s.add(subject)
        s.flush()
        for ident in identifiers:
            s.add(
                models.Identifier(
                    subject_id=subject.id,
                    type=ident.type.value,
                    value=ident.value,
                    ownership_verified=ident.ownership_verified,
                )
            )
        return subject.id


def run_and_store_scan(subject_id: str) -> str:
    """Run a full scan for a subject and persist results. Returns scan_id."""
    cfg = get_settings()

    with session_scope() as s:
        subject = s.get(models.Subject, subject_id)
        if subject is None:
            raise ValueError(f"subject {subject_id} not found")
        identifiers = [
            IdentifierSchema(
                type=InputType(i.type),
                value=i.value,
                ownership_verified=i.ownership_verified,
            )
            for i in subject.identifiers
        ]
        scan = models.Scan(subject_id=subject_id, status="running")
        s.add(scan)
        s.flush()
        scan_id = scan.id

    report = run_scan(identifiers, cfg)
    _persist_report(scan_id, report)
    return scan_id


def _persist_report(scan_id: str, report: ScanReport) -> None:
    with session_scope() as s:
        scan = s.get(models.Scan, scan_id)
        scan.config_snapshot = {
            "coverage_gaps": [g.model_dump() for g in report.coverage_gaps],
        }
        for jf in report.findings:
            signal_ids: list[str] = []
            for sig in jf.evidence.signals:
                row = models.Signal(
                    scan_id=scan_id,
                    source=sig.source,
                    kind=sig.kind,
                    locator=sig.locator,
                    raw=sig.raw,
                )
                s.add(row)
                s.flush()
                signal_ids.append(row.id)

            f = jf.finding
            finding_row = models.Finding(
                scan_id=scan_id,
                signal_ids=signal_ids,
                category=f.category.value,
                severity=f.severity.value,
                title=f.title,
                rationale=f.rationale,
                confidence=f.confidence,
            )
            s.add(finding_row)
            s.flush()

            if jf.remediation:
                r = jf.remediation
                s.add(
                    models.Remediation(
                        finding_id=finding_row.id,
                        tier=r.tier.value,
                        summary=r.summary,
                        steps=[step.model_dump() for step in r.steps],
                        artifact=r.artifact,
                    )
                )

        scan.status = "complete"
        scan.finished_at = datetime.now(timezone.utc)


def report_markdown(report: ScanReport) -> str:
    return render_markdown(report)
