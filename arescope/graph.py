"""Exposure Map builder — projects persisted findings into a node-link graph.

This is a *deterministic* projection of what we already store (Identifier +
Finding + Signal), rebuilt on every view — never hardcoded. Two properties make
it adapt as more analyses are added (docs/GRAPH.md §2):

  * **content-addressed node ids** — a site node's id IS its normalized platform,
    a breach node's id is the breach name. So the same platform reached by many
    inputs (even across separate scans) collapses to ONE node with many edges —
    convergence and dedup are automatic, never overlapping duplicates.
  * **severity flows from the Finding** — each edge is coloured by the severity of
    the finding its signal belongs to; a node inherits the worst severity touching it.

`build_scan_graph` maps one scan; `build_account_graph` merges every scan a user
owns into a single map (their whole footprint). Output is Cytoscape elements JSON.
"""

from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import select

from arescope.db import models
from arescope.db.session import session_scope
from arescope.schemas import SEVERITY_ORDER

_SEV_RANK = {s.value: r for s, r in SEVERITY_ORDER.items()}

# Domains whose Simple Icons slug differs from "first label of the domain".
_SLUG_OVERRIDE = {
    "twitter.com": "x",
    "x.com": "x",
    "office365.com": "microsoftoffice",
    "live.com": "microsoft",
    "outlook.com": "microsoftoutlook",
    "google.com": "google",
    "gmail.com": "gmail",
    "youtube.com": "youtube",
    "stackoverflow.com": "stackoverflow",
}


def _worse(a: str | None, b: str) -> str:
    """Return the higher-severity of two severity strings."""
    if a is None:
        return b
    return a if _SEV_RANK.get(a, 0) >= _SEV_RANK.get(b, 0) else b


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    netloc = urlparse(url if "//" in url else f"//{url}").netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc or None


def _platform_key(sig: models.Signal) -> str:
    """Stable platform id for a site/account signal — the convergence key."""
    raw = sig.raw or {}
    return (raw.get("domain") or _domain(raw.get("url")) or (sig.locator or "site")).lower()


def _slug(platform: str) -> str:
    if platform in _SLUG_OVERRIDE:
        return _SLUG_OVERRIDE[platform]
    return platform.split(".")[0] if "." in platform else platform


def _mask(value: str, itype: str) -> str:
    if itype == "email" and "@" in value:
        local, _, dom = value.partition("@")
        head = local[0] if local else ""
        return f"{head}{'•' * max(len(local) - 1, 1)}@{dom}"
    if itype in ("username", "name") and len(value) > 2:
        return value[:2] + "•" * (len(value) - 2)
    return value


def _classify(sig: models.Signal) -> tuple[str, dict] | None:
    """Map a signal to its (node_id, node_data). None => not mappable."""
    raw = sig.raw or {}
    if sig.source == "hibp":
        return f"breach:{sig.locator}", {
            "type": "breach",
            "label": raw.get("title") or sig.locator,
            "meta": {"date": raw.get("breach_date"), "data": raw.get("data_classes", [])},
        }
    if sig.source == "hudsonrock":
        return f"stealer:{sig.locator}", {
            "type": "stealer",
            "label": "Infostealer log",
            "meta": {"date": raw.get("date_compromised"), "machine": raw.get("computer_name")},
        }
    if sig.source == "shodan" and sig.kind == "host_profile":
        return f"iploc:{sig.locator}", {
            "type": "iploc",
            "label": raw.get("location") or "IP location",
            "meta": {
                "location": raw.get("location"),
                "isp": raw.get("isp"),
                "org": raw.get("org"),
                "open_ports": raw.get("open_ports", []),
            },
        }
    if sig.source == "shodan":
        return f"svc:{sig.locator}", {
            "type": "service",
            "label": f"{raw.get('product') or 'service'} :{raw.get('port')}",
            "meta": {"port": raw.get("port"), "vulns": raw.get("vulns", [])},
        }
    if sig.source in ("holehe", "maigret"):
        platform = _platform_key(sig)
        return f"site:{platform}", {
            "type": "site",
            "label": platform.split(".")[0].capitalize() if "." in platform else platform.capitalize(),
            "slug": _slug(platform),
            "url": raw.get("url"),
            "meta": {"platform": platform, "tags": raw.get("tags")},
        }
    return None


def _build(scan_ids: list[str], label: str) -> dict:
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}

    def put_node(node_id: str, severity: str | None = None, **data) -> None:
        n = nodes.get(node_id)
        if n is None:
            nodes[node_id] = {"data": {"id": node_id, **data}, "sev": severity}
        else:
            n["data"].update({k: v for k, v in data.items() if v is not None})
            n["sev"] = _worse(n["sev"], severity) if severity else n["sev"]

    def put_edge(src: str, dst: str, severity: str, info: str) -> None:
        eid = f"{src}->{dst}"
        if eid in edges:
            edges[eid]["data"]["severity"] = _worse(edges[eid]["data"]["severity"], severity)
        else:
            edges[eid] = {"data": {"id": eid, "source": src, "target": dst,
                                   "severity": severity, "info": info}}

    put_node("self", type="identity", label=label)

    with session_scope() as s:
        findings = (
            s.query(models.Finding).filter(models.Finding.scan_id.in_(scan_ids)).all()
            if scan_ids else []
        )
        for f in findings:
            sev = f.severity
            # input arm (the cluster subject) — content-addressed by value so the
            # same email/username across scans is ONE node.
            in_id = "self"
            if f.subject_value and f.subject_type:
                in_id = f"in:{f.subject_type}:{f.subject_value}"
                put_node(in_id, severity=sev, type="input", kind=f.subject_type,
                         label=_mask(f.subject_value, f.subject_type))
                put_edge("self", in_id, sev, "owns")

            sig_ids = f.signal_ids or []
            sigs = (
                s.execute(select(models.Signal).where(models.Signal.id.in_(sig_ids)))
                .scalars().all()
                if sig_ids else []
            )
            for sig in sigs:
                classified = _classify(sig)
                if classified is None:
                    continue
                node_id, ndata = classified
                put_node(node_id, severity=sev, **ndata)
                put_edge(in_id, node_id, sev, f.title)

    # flatten: hoist severity onto node data for styling
    out_nodes = []
    for n in nodes.values():
        n["data"]["severity"] = n["sev"] or "info"
        out_nodes.append({"data": n["data"]})

    return {
        "nodes": out_nodes,
        "edges": list(edges.values()),
        "counts": {"nodes": len(out_nodes), "edges": len(edges)},
    }


def build_scan_graph(scan_id: str) -> dict:
    return _build([scan_id], "you")


def build_account_graph(user_id: str, label: str = "you") -> dict:
    """Merge every scan the user owns into one map (their whole footprint)."""
    with session_scope() as s:
        scan_ids = [
            sid
            for sid, opts in s.execute(
                select(models.Scan.id, models.Scan.options)
                .join(models.Subject, models.Scan.subject_id == models.Subject.id)
                .where(models.Subject.user_id == user_id)
            ).all()
            # honour the per-scan "keep out of my map" toggle (e.g. a friend's scan)
            if not (opts or {}).get("exclude_from_map")
        ]
    return _build(scan_ids, label)
