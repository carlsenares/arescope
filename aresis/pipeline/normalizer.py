"""Normalizer / dedup (ARCHITECTURE.md §2 — plain code, not an LLM).

Merge Signals across sources keyed by (subject_value, subject_type, kind, locator)
into a deduped Evidence set. Cross-source agreement (e.g. holehe and maigret both
finding the same account) collapses into one Evidence carrying both sources.
"""

from __future__ import annotations

from collections import OrderedDict

from aresis.schemas import Evidence, Signal


def normalize(signals: list[Signal]) -> list[Evidence]:
    buckets: "OrderedDict[tuple, list[Signal]]" = OrderedDict()
    for sig in signals:
        key = (sig.subject_value, sig.subject_type, sig.kind, sig.locator.lower())
        buckets.setdefault(key, []).append(sig)

    evidence: list[Evidence] = []
    for (subject_value, subject_type, kind, _locator), group in buckets.items():
        sources = sorted({s.source for s in group})
        evidence.append(
            Evidence(
                subject_value=subject_value,
                subject_type=subject_type,
                kind=kind,
                locator=group[0].locator,  # preserve original casing
                sources=sources,
                signals=group,
            )
        )
    return evidence
