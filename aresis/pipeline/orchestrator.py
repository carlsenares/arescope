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
from aresis.pipeline.clustering import cluster_evidence
from aresis.pipeline.judge import judge_cluster
from aresis.pipeline.normalizer import normalize
from aresis.pipeline.report import ScanReport
from aresis.pipeline.triage import TriageItem, triage_clusters
from aresis.schemas import (
    SEVERITY_ORDER,
    ActionBucket,
    CoverageGap,
    EvidenceCluster,
    Identifier,
    JudgedFinding,
    Severity,
    Signal,
    Verdict,
)
from aresis.taxonomy import TAXONOMY

log = logging.getLogger("aresis.orchestrator")

# Triage severity at or above this escalates a cluster to the Opus judge.
_ESCALATE_AT = SEVERITY_ORDER[Severity.MEDIUM]


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


def _should_escalate(cluster: EvidenceCluster, item: TriageItem) -> bool:
    """Tier-0 hard rule OR Haiku's call OR provisional severity >= medium. Recall-biased."""
    return (
        cluster.force_escalate
        or item.escalate
        or SEVERITY_ORDER[item.severity] >= _ESCALATE_AT
    )


def _label_verdict(cluster: EvidenceCluster, item: TriageItem) -> Verdict:
    """Cheap verdict for a non-escalated (low/info) cluster, from the Haiku label.

    These populate the rolled-up tail of the report — no Opus call, no fix.
    """
    label = TAXONOMY[cluster.category_hint].label
    n = len(cluster.members)
    title = label if n == 1 else f"{label}: {n} items"
    action = (
        ActionBucket.NO_ACTION
        if item.severity in (Severity.INFO, Severity.LOW)
        else ActionBucket.WORTH_FIXING
    )
    return Verdict(
        category=cluster.category_hint,
        severity=item.severity,
        action=action,
        title=title,
        rationale=item.reason,
        confidence=0.5,
    )


def run_scan(identifiers: list[Identifier], cfg: Settings | None = None) -> ScanReport:
    cfg = cfg or get_settings()
    assert_ownership(identifiers)

    signals, gaps, _snapshot = collect_signals(identifiers, cfg)
    evidence = normalize(signals)
    clusters = cluster_evidence(evidence)          # Tier 0 — bounds Opus cost
    triage = triage_clusters(clusters)             # Tier 1 — Haiku recall net

    judged: list[JudgedFinding] = []
    for i, cluster in enumerate(clusters):
        item = triage[i]
        if _should_escalate(cluster, item):
            verdict = judge_cluster(cluster)       # Tier 2 — Opus deep judge
        else:
            verdict = _label_verdict(cluster, item)
        # No remediation here: easy fixes are inline in the verdict; involved fixes
        # are generated on demand (the paywall point).
        judged.append(JudgedFinding(verdict=verdict, cluster=cluster))

    return ScanReport(findings=judged, coverage_gaps=gaps)
