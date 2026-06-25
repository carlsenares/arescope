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

import hashlib
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


# Friendly source label for a web_mention node, keyed on the connector's sig.source.
_MENTION_SOURCE = {
    "tavily": "Web search",
    "brave": "Web search",
    "urlscan": "urlscan.io",
    "intelx": "Intelligence X",
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


def _slug_hash(ref: str) -> str:
    """Short stable id for a content-addressed node (e.g. a photo URL)."""
    return hashlib.md5((ref or "").encode()).hexdigest()[:12]  # noqa: S324 (id only, not security)


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
    # Any host_profile signal becomes the IP-location node — Shodan AND the IP
    # enrichers (IPinfo/AbuseIPDB/VirusTotal/Censys) all emit kind="host_profile"
    # keyed on the IP, so gating on source dropped IPinfo's location on the floor
    # (the "IP → location never showed on the map" bug). Same iploc:{ip} id => they
    # still merge into one node.
    if sig.kind == "host_profile":
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
    if sig.kind == "broker_listing":
        domain = (raw.get("domain") or sig.locator or "broker").lower()
        return f"broker:{domain}", {
            "type": "broker",
            "label": raw.get("broker") or domain,
            "slug": _slug(domain),
            "url": raw.get("listing_url"),
            "meta": {"domain": domain, "opt_out_url": raw.get("opt_out_url")},
        }
    if sig.kind == "identity_attribute":
        # The real-world facts a handle leaks. Photos and locations get their own map
        # nodes (visual, convergent); name/bio/company stay finding-only to avoid clutter.
        attribute = raw.get("attribute")
        value = raw.get("value") or ""
        if attribute == "photo":
            ref = raw.get("url") or value
            is_default = bool(raw.get("is_default"))
            return f"photo:{_slug_hash(ref)}", {
                "type": "photo",
                "label": "Default avatar" if is_default else "Profile photo",
                # only a REAL image is worth rendering as a thumbnail on the map;
                # a default monogram stays a plain node.
                "url": None if is_default else ref,
                "meta": {"platform": raw.get("platform"), "is_default": is_default},
            }
        if attribute == "location":
            return f"location:{value.lower()}", {
                "type": "location",
                "label": value if len(value) <= 40 else value[:39] + "…",
                "meta": {"platform": raw.get("platform")},
            }
        return None  # name/bio/company/link: surfaced in the finding, not the map

    if sig.kind == "web_mention":
        # Where the person is *mentioned* on the web (Tavily/Brave name search, urlscan,
        # IntelX leaks/pastes). Content-addressed by URL (else domain) so the same page
        # from two sources collapses to one node. The source label is derived from
        # sig.source (always present) rather than a per-connector raw field, so every
        # emitter renders consistently without each having to set it.
        url = raw.get("url") or ""
        domain = (raw.get("domain") or _domain(url) or "web").lower()
        return f"mention:{_slug_hash(url or domain)}", {
            "type": "mention",
            "label": (raw.get("title") or domain)[:60],
            "slug": _slug(domain),
            "url": url or None,
            "meta": {"domain": domain, "source": _MENTION_SOURCE.get(sig.source, sig.source),
                     "description": raw.get("description")},
        }

    if sig.kind == "account":
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


# --- Map mode: project raw Signals (no LLM judge) into the same graph ---------
#
# Map mode skips the Opus pipeline — it's about reach, not severity-rated findings.
# So we build straight from the persisted Signals (each carries its subject under
# reserved raw keys, since the Signal table has no subject columns) plus the
# subject's Identifiers as the input nodes. Colour comes from a cheap deterministic
# heuristic on the signal kind, not the judge — "advanced mapping, no Opus".

# kind -> map colour band (purely visual; no LLM). Reuses the severity palette.
_MAP_SEV_BY_KIND = {
    "stealer_log": "critical",
    "breach": "high",
    "exposed_service": "high",
    "host_profile": "low",
    "phone_risk": "medium",
    "phone_meta": "info",
    "account": "low",
    "web_mention": "info",
    "identity_attribute": "info",
    "broker_listing": "low",
}


def _map_sev(sig: models.Signal) -> str:
    raw = sig.raw or {}
    if sig.kind == "breach" and not raw.get("password_exposed") and not raw.get("data_classes"):
        return "low"
    if sig.kind == "host_profile" and (raw.get("vulns") or raw.get("abuse_score") or
                                       raw.get("malicious_engines")):
        return "high"
    if sig.kind == "phone_risk" and (raw.get("recent_abuse") or raw.get("leaked") or
                                     raw.get("spammer")):
        return "high"
    return _MAP_SEV_BY_KIND.get(sig.kind, "info")


def _post_nodes(sig: models.Signal) -> list[tuple[str, dict]]:
    """Project an account signal's `recent_posts` into content nodes (GRAPH.md §12).

    Posts/captions we already collect (Apify, Bluesky, Instagram) but never showed —
    they're the inference fuel the map is *for* (GRAPH.md §0). Each post becomes a
    content-addressed `post` node so the same caption across sources collapses to one.
    """
    raw = sig.raw or {}
    platform = (raw.get("domain") or "post").lower()
    out: list[tuple[str, dict]] = []
    for text in (raw.get("recent_posts") or []):
        text = str(text).strip()
        if not text:
            continue
        node_id = f"post:{_slug_hash(platform + ':' + text)}"
        out.append((node_id, {
            "type": "post",
            "label": text if len(text) <= 48 else text[:47] + "…",
            "meta": {"platform": platform, "text": text},
        }))
    return out


def _repo_nodes(sig: models.Signal) -> list[tuple[str, dict]]:
    """Project a GitHub account signal's `top_repos` into `repo` nodes — the public
    projects a dev handle exposes (tech, interests, sometimes employer). Content-
    addressed by repo URL so the same repo dedups."""
    out: list[tuple[str, dict]] = []
    for r in ((sig.raw or {}).get("top_repos") or []):
        if not isinstance(r, dict) or not r.get("name"):
            continue
        ref = r.get("url") or r["name"]
        out.append((f"repo:{_slug_hash(ref)}", {
            "type": "repo",
            "label": r["name"],
            "url": r.get("url"),
            "meta": {"description": r.get("description"), "stars": r.get("stars"),
                     "language": r.get("language")},
        }))
    return out


def build_map_graph(scan_id: str, label: str = "you") -> dict:
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
        scan = s.get(models.Scan, scan_id)
        subject = s.get(models.Subject, scan.subject_id) if scan else None
        in_ids: dict[tuple[str, str], str] = {}
        for ident in (subject.identifiers if subject else []):
            in_id = f"in:{ident.type}:{ident.value}"
            in_ids[(ident.type, ident.value)] = in_id
            # The map is the owner auditing THEIR OWN footprint — masking their own
            # inputs just made the labels unreadable ("ad•••"). Show them in full.
            # (_mask stays for build_scan_graph / future shared-service views.)
            put_node(in_id, type="input", kind=ident.type, label=ident.value)
            put_edge("self", in_id, "info", "owns")

        sigs = s.query(models.Signal).filter(models.Signal.scan_id == scan_id).all()
        for sig in sigs:
            classified = _classify(sig)
            if classified is None:
                continue
            node_id, ndata = classified
            sev = _map_sev(sig)
            put_node(node_id, severity=sev, **ndata)
            raw = sig.raw or {}
            in_id = in_ids.get((raw.get("__subject_type"), raw.get("__subject_value")), "self")
            put_edge(in_id, node_id, sev, sig.source)
            # Hang each collected post / public repo off its platform node so the
            # content shows (the inference fuel the map is for).
            if sig.kind == "account":
                for post_id, pdata in _post_nodes(sig):
                    put_node(post_id, severity="info", **pdata)
                    put_edge(node_id, post_id, "info", "posted")
                for repo_id, rdata in _repo_nodes(sig):
                    put_node(repo_id, severity="info", **rdata)
                    put_edge(node_id, repo_id, "info", "repo")

    out_nodes = []
    for n in nodes.values():
        n["data"]["severity"] = n["sev"] or "info"
        out_nodes.append({"data": n["data"]})
    return {"nodes": out_nodes, "edges": list(edges.values()),
            "counts": {"nodes": len(out_nodes), "edges": len(edges)}}
