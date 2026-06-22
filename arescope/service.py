"""Service layer: bridges the stateless engine to persistence.

Creates subjects/identifiers, runs the engine, and writes signals/findings/
remediations with a retention TTL. Kept separate from orchestrator.py so the
engine stays stateless and unit-testable.
"""

from __future__ import annotations

from datetime import datetime, timezone

from arescope.config import get_settings
from arescope.db import models
from arescope.db.session import session_scope
from arescope.connectors.registry import available_connectors
from arescope.pipeline.orchestrator import (
    judge_signals,
    run_connectors,
    unavailable_gaps,
)
from arescope.pipeline.remediation import generate_remediation
from arescope.pipeline.report import ScanReport, render_markdown
from arescope.pipeline.resolution import resolve
from arescope.schemas import (
    ActionBucket,
    Category,
    ContingencyQuestion,
    EvidenceCluster,
    FixDifficulty,
    JudgedFinding,
    Remediation,
    Severity,
    Verdict,
)
from arescope.schemas import Identifier as IdentifierSchema
from arescope.schemas import InputType


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


def create_scan(subject_id: str, options: dict | None = None, name: str | None = None) -> str:
    """Create a queued scan row so it's visible the instant the user submits.

    The worker picks it up and runs it; splitting create from run means the
    dashboard shows a real record even before a worker is free. `options` carries
    per-run choices (e.g. {"maigret_top_sites": 50}); `name` is the user's label.
    """
    with session_scope() as s:
        subject = s.get(models.Subject, subject_id)
        if subject is None:
            raise ValueError(f"subject {subject_id} not found")
        scan = models.Scan(
            subject_id=subject_id, status="queued", options=options or {}, name=name or None
        )
        s.add(scan)
        s.flush()
        return scan.id


def run_and_store_scan(scan_id: str) -> str:
    """Run a queued scan in waves and persist each finding the moment it's judged.

    Wave 1 = the fast sources (HIBP / Hudson Rock / Holehe / Shodan); wave 2 =
    Maigret's slow username search. Each cluster's Opus verdict is written as its
    own row immediately, so the results page streams findings in as they land and
    a user can act on one while the rest are still running.
    """
    cfg = get_settings()

    with session_scope() as s:
        scan = s.get(models.Scan, scan_id)
        if scan is None:
            raise ValueError(f"scan {scan_id} not found")
        subject = s.get(models.Subject, scan.subject_id)
        if subject is None:
            raise ValueError(f"subject {scan.subject_id} not found")
        identifiers = [
            IdentifierSchema(
                type=InputType(i.type),
                value=i.value,
                ownership_verified=i.ownership_verified,
            )
            for i in subject.identifiers
        ]
        options = dict(scan.options or {})
        scan.status = "running"

    top = options.get("maigret_top_sites")
    if top:
        cfg = cfg.model_copy(update={"maigret_top_sites": int(top)})

    available = available_connectors(cfg)
    gaps = unavailable_gaps(cfg)
    fast = [c for c in available if c.name != "maigret"]
    slow = [c for c in available if c.name == "maigret"]
    has_username = any(i.type is InputType.USERNAME for i in identifiers)

    # Wave 1 — fast sources, streamed.
    signals, run_gaps = run_connectors(identifiers, cfg, fast)
    gaps += run_gaps
    for jf in judge_signals(signals):
        _persist_one_finding(scan_id, jf)

    # Wave 2 — the slow username search (only does work when a username is present).
    if slow and has_username:
        _set_phase(scan_id, "Searching your username across sites…")
        sig2, gap2 = run_connectors(identifiers, cfg, slow)
        gaps += gap2
        for jf in judge_signals(sig2):
            _persist_one_finding(scan_id, jf)

    _finalize_scan(scan_id, gaps)
    return scan_id


def _persist_one_finding(scan_id: str, jf: JudgedFinding) -> None:
    """Write a single judged finding (+ its signals) in its own transaction."""
    with session_scope() as s:
        v = jf.verdict
        signal_ids: list[str] = []
        for ev in jf.cluster.members:
            for sig in ev.signals:
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

        finding_row = models.Finding(
            scan_id=scan_id,
            signal_ids=signal_ids,
            category=v.category.value,
            severity=v.severity.value,
            title=v.title,
            rationale=v.rationale,
            confidence=v.confidence,
            action=v.action.value,
            fix_difficulty=v.fix_difficulty.value if v.fix_difficulty else None,
            easy_fix=v.easy_fix,
            questions=[q.model_dump() for q in v.questions],
            member_locators=jf.cluster.member_locators,
            subject_type=jf.cluster.subject_type.value,
            subject_value=jf.cluster.subject_value,
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


def _set_phase(scan_id: str, phase: str) -> None:
    """Record a human-readable progress phase the results page can show."""
    with session_scope() as s:
        scan = s.get(models.Scan, scan_id)
        if scan is not None:
            snap = dict(scan.config_snapshot or {})
            snap["phase"] = phase
            scan.config_snapshot = snap


def _finalize_scan(scan_id: str, gaps: list) -> None:
    with session_scope() as s:
        scan = s.get(models.Scan, scan_id)
        if scan is None:
            return
        scan.config_snapshot = {"coverage_gaps": [g.model_dump() for g in gaps]}
        scan.status = "complete"
        scan.finished_at = datetime.now(timezone.utc)


def report_markdown(report: ScanReport) -> str:
    return render_markdown(report)


# --- On-demand: reconstruct engine units from a persisted Finding row ---------
#
# After a scan the verdict is flattened into columns + separate Signal rows. The
# two on-demand actions (generate an involved remediation, resolve a DEPENDS
# finding) need the in-memory schemas back. resolve() only touches the verdict;
# generate_remediation() reads member_locators + the subject — both persisted —
# so a members-less cluster is sufficient and we avoid rehydrating every signal.


def _verdict_from_row(f: models.Finding) -> Verdict:
    return Verdict(
        category=Category(f.category),
        severity=Severity(f.severity),
        action=ActionBucket(f.action),
        title=f.title,
        rationale=f.rationale,
        confidence=f.confidence,
        fix_difficulty=FixDifficulty(f.fix_difficulty) if f.fix_difficulty else None,
        easy_fix=f.easy_fix,
        questions=[ContingencyQuestion.model_validate(q) for q in (f.questions or [])],
    )


def _cluster_from_row(f: models.Finding) -> EvidenceCluster:
    return EvidenceCluster(
        signature=f.id,
        category_hint=Category(f.category),
        subject_value=f.subject_value or "",
        subject_type=InputType(f.subject_type) if f.subject_type else InputType.EMAIL,
        kind=f.category,
        members=[],
        member_locators=f.member_locators or [],
    )


def generate_finding_remediation(finding_id: str) -> Remediation:
    """Generate (or regenerate) the involved fix for one finding. The paywall point.

    The Opus call runs outside the DB session; we persist the result as the
    finding's single remediation (upsert).
    """
    with session_scope() as s:
        f = s.get(models.Finding, finding_id)
        if f is None:
            raise ValueError(f"finding {finding_id} not found")
        verdict = _verdict_from_row(f)
        cluster = _cluster_from_row(f)

    rem = generate_remediation(verdict, cluster)

    with session_scope() as s:
        f = s.get(models.Finding, finding_id)
        if f is None:
            raise ValueError(f"finding {finding_id} not found")
        existing = f.remediation
        steps = [step.model_dump() for step in rem.steps]
        if existing is not None:
            existing.tier = rem.tier.value
            existing.summary = rem.summary
            existing.steps = steps
            existing.artifact = rem.artifact
        else:
            s.add(
                models.Remediation(
                    finding_id=finding_id,
                    tier=rem.tier.value,
                    summary=rem.summary,
                    steps=steps,
                    artifact=rem.artifact,
                )
            )
    return rem


def resolve_finding(finding_id: str, answers: dict[int, bool]) -> Verdict:
    """Apply yes/no answers to a DEPENDS finding — deterministic, free, no LLM.

    Persists the resolved severity/action/rationale and clears the questions.
    Returns the resolved verdict (unchanged if the finding wasn't contingent).
    """
    with session_scope() as s:
        f = s.get(models.Finding, finding_id)
        if f is None:
            raise ValueError(f"finding {finding_id} not found")
        jf = JudgedFinding(verdict=_verdict_from_row(f), cluster=_cluster_from_row(f))
        rv = resolve(jf, answers).verdict
        f.severity = rv.severity.value
        f.action = rv.action.value
        f.rationale = rv.rationale
        f.questions = [q.model_dump() for q in rv.questions]
        f.fix_difficulty = rv.fix_difficulty.value if rv.fix_difficulty else None
        return rv
