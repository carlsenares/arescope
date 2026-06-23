"""Service layer: bridges the stateless engine to persistence.

Creates subjects/identifiers, runs the engine, and writes signals/findings/
remediations with a retention TTL. Kept separate from orchestrator.py so the
engine stays stateless and unit-testable.
"""

from __future__ import annotations

from datetime import datetime, timezone

import json

from arescope.config import get_settings
from arescope.db import models
from arescope.db.session import session_scope
from arescope.connectors.registry import available_connectors
from arescope.graph import build_account_graph, build_scan_graph
from arescope.pipeline.chat import answer as chat_answer
from arescope.pipeline.orchestrator import (
    judge_signals,
    run_connectors,
    stream_connectors,
    uncovered_input_gaps,
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
        # Admins bypass the self-audit ownership gate (DEEP_SEARCH_PLAN.md §safety
        # frame: "Admin bypasses the gate — can audit anything"), so they get the
        # extended name tier without a verified-email link.
        owner = s.get(models.User, subject.user_id) if subject.user_id else None
        owner_is_admin = bool(owner and owner.is_admin)
        scan.status = "running"

    # From here on the scan is marked "running"; any unhandled error must flip it to
    # "failed" (with finished_at) — otherwise the task dies, the row stays "running"
    # forever, and the results page polls /status indefinitely (looks like a hang).
    try:
        top = options.get("maigret_top_sites")
        if top:
            cfg = cfg.model_copy(update={"maigret_top_sites": int(top)})

        # Extended (dossier) name tier — "name + verified email => extended results".
        # For regular users it's gated on verified ownership of a linked email (the P2
        # gate, docs/OWNERSHIP_VERIFICATION.md), which isn't built yet, so it stays OFF:
        # a name-only scan returns broker-listing existence + the removal track, never a
        # dossier. ADMINS bypass the gate and always get extended. When the gate lands,
        # OR the admin check in here with the verified-ownership check for regular users.
        if owner_is_admin:
            cfg = cfg.model_copy(update={"name_extended": True})

        available = available_connectors(cfg)
        # Admin-only sources (broad web search / scraping / reverse face) never run for
        # regular users — the self-audit hard rule (EXTENDED_SEARCH_SCOPE.md). Until the
        # per-input ownership gate lands this is the line that keeps the heavy connectors
        # admin-bound. They're simply absent for non-admins (not even a coverage gap —
        # a regular user was never entitled to them, so it's not "missing coverage").
        if not owner_is_admin:
            available = [c for c in available if not c.admin_only]
        gaps = unavailable_gaps(cfg) + uncovered_input_gaps(identifiers, cfg)
        # Which of the inputs the user gave actually have a source that searches them.
        # If this ends up empty (e.g. a name-only scan), a clean report must NOT read as
        # "Nothing exposed" — we searched nothing. The results page uses this to be honest.
        covered_types = set().union(*(c.consumes for c in available)) if available else set()
        searched_types = sorted({i.type.value for i in identifiers if i.type in covered_types})
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

        _finalize_scan(scan_id, gaps, searched_types)
    except Exception:
        _fail_scan(scan_id)
        raise
    return scan_id


def run_and_store_map(scan_id: str) -> str:
    """Map mode (no Opus): run every available connector across ALL the subject's
    identifiers, persist the raw Signals, and let graph.build_map_graph project them.

    Skips clustering/triage/judge entirely — map mode is about reach, not severity-
    rated findings, so it's just collection + projection. Each Signal stashes its
    subject under reserved raw keys (the Signal table has no subject columns) so the
    graph can wire it to the right input node.
    """
    cfg = get_settings()
    with session_scope() as s:
        scan = s.get(models.Scan, scan_id)
        if scan is None:
            raise ValueError(f"scan {scan_id} not found")
        subject = s.get(models.Subject, scan.subject_id)
        identifiers = [
            IdentifierSchema(type=InputType(i.type), value=i.value,
                             ownership_verified=i.ownership_verified)
            for i in subject.identifiers
        ]
        owner = s.get(models.User, subject.user_id) if subject.user_id else None
        owner_is_admin = bool(owner and owner.is_admin)
        scan.status = "running"

    # Map mode caps Maigret to the popular sites by default — a multi-input map can't
    # wait minutes per username (full Maigret is the audit-mode opt-in).
    cfg = cfg.model_copy(update={"maigret_top_sites": cfg.maigret_top_sites or 50})

    try:
        available = available_connectors(cfg)
        if not owner_is_admin:
            available = [c for c in available if not c.admin_only]
        covered = set().union(*(c.consumes for c in available)) if available else set()
        searched = sorted({i.type.value for i in identifiers if i.type in covered})
        # Fast sources first so the graph fills immediately; slow scrapers/enumerators
        # (Maigret/Sherlock/Apify/Ignorant/PhoneInfoga) stream in after.
        available.sort(key=lambda c: c.name in _SLOW_SOURCES)

        gaps = unavailable_gaps(cfg) + uncovered_input_gaps(identifiers, cfg)
        total = 0
        for cname, sigs, gap in stream_connectors(identifiers, cfg, available):
            if gap is not None:
                gaps.append(gap)
            if sigs:
                # Persist this connector's batch in its own txn — the moment it commits,
                # the next /graph poll picks the new nodes up and streams them in.
                with session_scope() as s:
                    for sig in sigs:
                        raw = dict(sig.raw or {})
                        raw["__subject_value"] = sig.subject_value
                        raw["__subject_type"] = sig.subject_type.value
                        s.add(models.Signal(scan_id=scan_id, source=sig.source,
                                            kind=sig.kind, locator=sig.locator, raw=raw))
                total += len(sigs)
            _set_phase(scan_id, f"Mapping — {cname} ({total} signals so far)…")
        _finalize_scan(scan_id, gaps, searched)
    except Exception:
        _fail_scan(scan_id)
        raise
    return scan_id


# Connectors whose latency warrants running last in a streaming map build.
_SLOW_SOURCES = {"maigret", "sherlock", "apify", "ignorant", "phoneinfoga"}


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
            problem=v.problem or None,
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


def _finalize_scan(scan_id: str, gaps: list, searched_types: list[str] | None = None) -> None:
    with session_scope() as s:
        scan = s.get(models.Scan, scan_id)
        if scan is None:
            return
        scan.config_snapshot = {
            "coverage_gaps": [g.model_dump() for g in gaps],
            "searched_types": searched_types or [],
        }
        scan.status = "complete"
        scan.finished_at = datetime.now(timezone.utc)


def _fail_scan(scan_id: str) -> None:
    """Mark a scan failed so the results page stops polling. Findings already
    persisted before the failure are kept — the user still sees partial results."""
    with session_scope() as s:
        scan = s.get(models.Scan, scan_id)
        if scan is None:
            return
        scan.status = "failed"
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
        problem=f.problem or "",
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


def generate_finding_artifact(finding_id: str) -> Remediation:
    """Draft the ready-to-send request (GDPR/opt-out/takedown) for a finding.

    The second, explicit step after advice: only fired when the user chooses to
    send a request, so Arescope never auto-drafts on the user's behalf. Keeps the
    existing advice (summary/steps) and fills in just the artifact.
    """
    with session_scope() as s:
        f = s.get(models.Finding, finding_id)
        if f is None:
            raise ValueError(f"finding {finding_id} not found")
        verdict = _verdict_from_row(f)
        cluster = _cluster_from_row(f)

    rem = generate_remediation(verdict, cluster, with_artifact=True)

    with session_scope() as s:
        f = s.get(models.Finding, finding_id)
        if f is None:
            raise ValueError(f"finding {finding_id} not found")
        existing = f.remediation
        if existing is not None:
            # Keep the advice the user already saw; add the drafted request to it.
            existing.artifact = rem.artifact
            existing.tier = rem.tier.value
        else:
            s.add(
                models.Remediation(
                    finding_id=finding_id,
                    tier=rem.tier.value,
                    summary=rem.summary,
                    steps=[step.model_dump() for step in rem.steps],
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


# --- Ask-Opus chat (persisted mini-threads about a finding or the map) --------


def load_chat(user_id: str, scope: str) -> list[dict]:
    """The thread for (user, scope), oldest first: [{role, content}, ...]."""
    with session_scope() as s:
        rows = (
            s.query(models.ChatMessage)
            .filter(models.ChatMessage.user_id == user_id, models.ChatMessage.scope == scope)
            .order_by(models.ChatMessage.created_at.asc())
            .all()
        )
        return [{"role": r.role, "content": r.content} for r in rows]


def _finding_chat_context(finding_id: str) -> str:
    """The full picture Opus needs to answer about one finding."""
    with session_scope() as s:
        f = s.get(models.Finding, finding_id)
        if f is None:
            raise ValueError(f"finding {finding_id} not found")
        sigs = (
            s.query(models.Signal).filter(models.Signal.id.in_(f.signal_ids or [])).all()
            if f.signal_ids
            else []
        )
        lines = [
            f"Finding: {f.title}",
            f"Category: {f.category} | Severity: {f.severity} | Action: {f.action}",
            f"Problem: {f.problem or '—'}",
            f"What it means: {f.rationale}",
        ]
        if f.easy_fix:
            lines.append(f"Inline quick fix: {f.easy_fix}")
        if f.member_locators:
            lines.append(f"Exposed on: {', '.join(f.member_locators[:40])}")
        if f.questions:
            lines.append(f"Open contingency questions: {json.dumps(f.questions)}")
        lines.append("\nRaw source records Opus was given (the exact data found):")
        for sig in sigs[:20]:
            lines.append(
                f"- [{sig.source}/{sig.kind}] {sig.locator}: "
                f"{json.dumps(sig.raw or {}, default=str)}"
            )
        return "\n".join(lines)


def _summarize_graph(elements: dict, selection: list[str] | None) -> str:
    """Compact text rendering of the exposure map so Opus can reason over it."""
    nodes = {n["data"]["id"]: n["data"] for n in elements.get("nodes", [])}
    lines = [
        f"The user's exposure map: {len(nodes)} nodes, "
        f"{len(elements.get('edges', []))} connections, centred on their identity.",
        "Nodes (label · type · worst severity touching it):",
    ]
    for d in list(nodes.values())[:80]:
        lines.append(f"- {d.get('label', d['id'])} · {d.get('type')} · {d.get('severity')}")
    lines.append("Connections (what links to what, and the risk colour):")
    for e in elements.get("edges", [])[:120]:
        d = e["data"]
        src = nodes.get(d["source"], {}).get("label", d["source"])
        dst = nodes.get(d["target"], {}).get("label", d["target"])
        lines.append(f"- {src} → {dst} ({d.get('info', 'link')}, {d.get('severity')})")
    if selection:
        lines.append(f"\nThe user has highlighted these nodes to ask about: {', '.join(selection)}")
    return "\n".join(lines)


def _map_chat_context(user_id: str, scan_id: str | None, selection: list[str] | None) -> str:
    elements = build_scan_graph(scan_id) if scan_id else build_account_graph(user_id)
    return _summarize_graph(elements, selection)


def _persist_turn(user_id: str, scope: str, role: str, content: str) -> None:
    with session_scope() as s:
        s.add(models.ChatMessage(user_id=user_id, scope=scope, role=role, content=content))


def send_finding_chat(user_id: str, finding_id: str, question: str) -> str:
    """Persist the question, answer it with the finding's context, persist the reply."""
    scope = f"finding:{finding_id}"
    context = _finding_chat_context(finding_id)
    history = load_chat(user_id, scope)
    reply = chat_answer(context, history, question)
    _persist_turn(user_id, scope, "user", question)
    _persist_turn(user_id, scope, "assistant", reply)
    return reply


def send_map_chat(
    user_id: str, scan_id: str | None, question: str, selection: list[str] | None = None
) -> str:
    """Answer a question about the exposure map (a scan's, or the whole account's)."""
    scope = f"map:scan:{scan_id}" if scan_id else "map:account"
    context = _map_chat_context(user_id, scan_id, selection)
    history = load_chat(user_id, scope)
    reply = chat_answer(context, history, question)
    _persist_turn(user_id, scope, "user", question)
    _persist_turn(user_id, scope, "assistant", reply)
    return reply
