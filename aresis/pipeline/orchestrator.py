"""The scan engine (ARCHITECTURE.md §4.1 — stateless).

Takes a set of owned identifiers + config and returns a ScanReport. No
single-user assumptions: this is pure engine, callable from the Celery task, a
test, or a future multi-tenant service. The ownership gate is asserted (no-op)
in P0; the hook is here so P2 can make it mandatory.
"""

from __future__ import annotations

import logging

from aresis.config import Settings, get_settings
from aresis.connectors.base import ConnectorGap, ConnectorUnavailable
from aresis.connectors.registry import available_connectors, REGISTRY
from aresis.pipeline.judge import judge
from aresis.pipeline.normalizer import normalize
from aresis.pipeline.remediation import remediate
from aresis.pipeline.report import ScanReport
from aresis.schemas import (
    CoverageGap,
    Identifier,
    JudgedFinding,
    Severity,
    Signal,
)

log = logging.getLogger("aresis.orchestrator")


def assert_ownership(identifiers: list[Identifier]) -> None:
    """P0 ownership gate: no-op (operator asserts ownership). P2 makes it real."""
    # Pluggable strategy seam (ARCHITECTURE.md §4.2). In P2 this becomes
    # VerifyOwnership and raises on unverified identifiers.
    return None


def collect_signals(
    identifiers: list[Identifier], cfg: Settings
) -> tuple[list[Signal], list[CoverageGap], dict]:
    """Route each identifier to the connectors that consume it; tolerate failures."""
    signals: list[Signal] = []
    gaps: list[CoverageGap] = []
    ran: list[str] = []
    enabled = available_connectors(cfg)

    # Connectors present but not configured/enabled => honest coverage gap.
    for connector in REGISTRY:
        if connector not in enabled:
            gaps.append(CoverageGap(source=connector.name, reason="not configured / disabled"))

    for connector in enabled:
        used = False
        for ident in identifiers:
            if ident.type not in connector.consumes:
                continue
            used = True
            try:
                signals.extend(connector.run(ident.value, ident.type, cfg))
            except (ConnectorGap, ConnectorUnavailable) as e:
                gaps.append(CoverageGap(source=connector.name, reason=str(e)))
            except Exception as e:  # never let one connector sink the scan
                log.exception("connector %s crashed", connector.name)
                gaps.append(CoverageGap(source=connector.name, reason=f"unexpected error: {e}"))
        if used:
            ran.append(connector.name)

    config_snapshot = {
        "connectors_ran": ran,
        "connectors_skipped": [g.source for g in gaps],
    }
    return signals, gaps, config_snapshot


def run_scan(identifiers: list[Identifier], cfg: Settings | None = None) -> ScanReport:
    cfg = cfg or get_settings()
    assert_ownership(identifiers)

    signals, gaps, _snapshot = collect_signals(identifiers, cfg)
    evidence = normalize(signals)

    judged: list[JudgedFinding] = []
    for ev in evidence:
        finding = judge(ev)
        remediation = None
        if finding.severity is not Severity.INFO:
            remediation = remediate(finding, ev)
        judged.append(JudgedFinding(finding=finding, evidence=ev, remediation=remediation))

    return ScanReport(findings=judged, coverage_gaps=gaps)
