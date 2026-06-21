"""The scan engine (ARCHITECTURE.md §4.1 — stateless).

Takes a set of owned identifiers + config and returns a ScanReport. No
single-user assumptions: this is pure engine, callable from the Celery task, a
test, or a future multi-tenant service. The ownership gate is asserted (no-op)
in P0; the hook is here so P2 can make it mandatory.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from arescope.config import Settings, get_settings
from arescope.connectors.base import ConnectorGap, ConnectorUnavailable
from arescope.connectors.registry import available_connectors, REGISTRY
from arescope.pipeline.clustering import cluster_evidence
from arescope.pipeline.judge import judge_cluster
from arescope.pipeline.normalizer import normalize
from arescope.pipeline.report import ScanReport
from arescope.pipeline.triage import TriageItem, triage_clusters
from arescope.schemas import (
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
from arescope.taxonomy import TAXONOMY

log = logging.getLogger("arescope.orchestrator")

# Triage severity at or above this escalates a cluster to the Opus judge.
_ESCALATE_AT = SEVERITY_ORDER[Severity.MEDIUM]


def assert_ownership(identifiers: list[Identifier]) -> None:
    """P0 ownership gate: no-op (operator asserts ownership). P2 makes it real."""
    # Pluggable strategy seam (ARCHITECTURE.md §4.2). In P2 this becomes
    # VerifyOwnership and raises on unverified identifiers.
    return None


def unavailable_gaps(cfg: Settings) -> list[CoverageGap]:
    """Connectors present in the registry but not configured/enabled — honest gaps."""
    enabled = available_connectors(cfg)
    return [
        CoverageGap(source=c.name, reason="not configured / disabled")
        for c in REGISTRY
        if c not in enabled
    ]


def run_connectors(
    identifiers: list[Identifier], cfg: Settings, connectors: list
) -> tuple[list[Signal], list[CoverageGap]]:
    """Run a specific set of connectors over the identifiers; tolerate failures.

    Splitting this out lets the service run connectors in waves (fast sources
    first, slow username search after) and stream findings as each wave lands.
    """
    signals: list[Signal] = []
    gaps: list[CoverageGap] = []
    for connector in connectors:
        for ident in identifiers:
            if ident.type not in connector.consumes:
                continue
            try:
                signals.extend(connector.run(ident.value, ident.type, cfg))
            except (ConnectorGap, ConnectorUnavailable) as e:
                gaps.append(CoverageGap(source=connector.name, reason=str(e)))
            except Exception as e:  # never let one connector sink the scan
                log.exception("connector %s crashed", connector.name)
                gaps.append(CoverageGap(source=connector.name, reason=f"unexpected error: {e}"))
    return signals, gaps


def judge_signals(signals: list[Signal]) -> Iterator[JudgedFinding]:
    """Cluster a batch of signals and yield one JudgedFinding per cluster.

    Opus judges each cluster independently, so we yield them one at a time —
    the service persists each the moment it's ready, and the UI streams it in.
    """
    evidence = normalize(signals)
    clusters = cluster_evidence(evidence)
    triage = triage_clusters(clusters)
    for i, cluster in enumerate(clusters):
        item = triage[i]
        if _should_escalate(cluster, item):
            verdict = judge_cluster(cluster)
        else:
            verdict = _label_verdict(cluster, item)
        yield JudgedFinding(verdict=verdict, cluster=cluster)


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
    """All-at-once scan (CLI + tests). The streaming web path lives in the service."""
    cfg = cfg or get_settings()
    assert_ownership(identifiers)

    available = available_connectors(cfg)
    gaps = unavailable_gaps(cfg)
    signals, run_gaps = run_connectors(identifiers, cfg, available)
    gaps += run_gaps
    judged = list(judge_signals(signals))
    return ScanReport(findings=judged, coverage_gaps=gaps)
