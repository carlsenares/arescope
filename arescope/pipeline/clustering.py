"""Tier 0 — deterministic clustering + hard-escalation (AI_PIPELINE.md).

Collapses similar evidence into clusters so the judge sees ~10 units, not ~270.
This is what actually bounds Opus cost on pathological inputs (test@example.com:
257 breaches -> a handful of clusters). Pure code: no LLM, fully testable, and
the escalation rules are legible to a reviewer.

Hard rule: this layer NEVER drops an item. It groups and it may force-escalate;
every cluster still flows to the triage net downstream.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone

from arescope.schemas import Category, Evidence, EvidenceCluster, InputType

# Breach data classes that actually raise severity, mapped to a coarse tag.
_SALIENT = {
    "Passwords": "password",
    "Historical passwords": "password",
    "Credit cards": "financial",
    "Bank account numbers": "financial",
    "Social security numbers": "govid",
    "Government issued IDs": "govid",
    "Physical addresses": "address",
    "Phone numbers": "phone",
    "Dates of birth": "dob",
}

# Ports whose mere exposure warrants a deep look (admin/data-plane services).
_SENSITIVE_PORTS = {23, 3389, 3306, 5432, 27017, 6379, 9200, 5900, 11211, 1433}

_RECENT_YEARS = 3


def _breach_tags(raw: dict) -> list[str]:
    classes = raw.get("data_classes") or []
    tags = {_SALIENT[c] for c in classes if c in _SALIENT}
    return sorted(tags)


def _recency_band(raw: dict) -> str:
    date = raw.get("breach_date") or ""
    try:
        year = int(str(date)[:4])
    except (ValueError, TypeError):
        return "unknown"
    age = datetime.now(timezone.utc).year - year
    return "recent" if age <= _RECENT_YEARS else "old"


def _classify(ev: Evidence) -> tuple[str, Category, bool, str | None]:
    """-> (signature, category_hint, force_escalate, escalate_reason)."""
    raw = ev.signals[0].raw if ev.signals else {}

    if ev.kind == "stealer_log":
        # All stealer logs for a subject are one infection story; always critical.
        return (
            f"stealer|{ev.subject_value}",
            Category.INFOSTEALER_INFECTION,
            True,
            "infostealer log implies live credential + session theft",
        )

    if ev.kind == "breach":
        # Cluster by COARSE risk tier, not the exact data-class set — otherwise
        # every combination becomes its own cluster. The exact classes still reach
        # the judge as member detail; they just don't define cluster boundaries.
        tags = _breach_tags(raw)
        band = _recency_band(raw)
        if "financial" in tags or "govid" in tags:
            tier, reason = "sensitive", "breach exposed financial / government-ID data"
        elif "password" in tags:
            tier = "password"
            reason = "recent breach exposed a password" if band == "recent" else "breach exposed a password"
        elif "address" in tags:
            tier, reason = "address", "breach exposed a home address (doxxing risk)"
        else:
            tier, reason = "minor", None
        has_pw = tier == "password"
        category = Category.CREDENTIAL_EXPOSURE if has_pw else Category.BREACH_MEMBERSHIP
        force = tier != "minor"
        return f"breach|{tier}|{band}", category, force, reason

    if ev.kind == "account":
        # Footprint (email) vs username correlation; one cluster each per subject.
        if ev.subject_type is InputType.USERNAME:
            return (
                f"account|username|{ev.subject_value}",
                Category.USERNAME_CORRELATION,
                False,
                None,
            )
        return f"account|email|{ev.subject_value}", Category.ACCOUNT_FOOTPRINT, False, None

    if ev.kind == "exposed_service":
        port = raw.get("port")
        vulns = raw.get("vulns") or []
        force = bool(vulns) or (isinstance(port, int) and port in _SENSITIVE_PORTS)
        reason = None
        if force:
            reason = "known CVE on the service" if vulns else f"sensitive service exposed (port {port})"
        return f"infra|{ev.subject_value}", Category.EXPOSED_INFRASTRUCTURE, force, reason

    if ev.kind == "broker_listing":
        # Every broker for this name is one "data-broker exposure" story → one cluster
        # per name, which the judge rates and routes to the T1 removal artifact.
        # Force-escalate so Opus writes a proper verdict + opt-out plan, not a cheap label.
        # `confirmed` distinguishes a paid lookup (the name IS listed) from the free
        # enumeration catalog (these brokers MAY list the name) — the judge must not
        # overstate the latter.
        confirmed = bool(raw.get("confirmed", True))
        reason = (
            "name is listed on these data-broker / people-search sites (removal recommended)"
            if confirmed
            else "major people-search brokers the name may be listed on — enumeration, NOT "
            "confirmed for this person; frame as a removal/opt-out checklist, not proven exposure"
        )
        return (f"broker|{ev.subject_value}", Category.DATA_BROKER_LISTING, True, reason)

    if ev.kind == "identity_attribute":
        # What a handle/email reveals about the real person (name/location/photo/bio).
        # Photos are their own story (face/photo exposure); everything else is the
        # identity-metadata finding. One cluster each per subject so the judge writes
        # "your handle exposes your real name + city + employer", not N tiny findings.
        attribute = raw.get("attribute")
        if attribute == "photo":
            return f"photo|{ev.subject_value}", Category.FACE_PHOTO_EXPOSURE, False, None
        return f"identity|{ev.subject_value}", Category.ACCOUNT_METADATA, False, None

    if ev.kind == "web_mention":
        # Public web pages that surface a name (news, records, profiles). One cluster
        # per name — "your name appears on N public pages" — judged as identity
        # metadata. Let triage rate it (usually low-medium); not force-escalated.
        return f"webmention|{ev.subject_value}", Category.ACCOUNT_METADATA, False, None

    if ev.kind == "host_profile":
        # What the IP reveals (location, ISP, hostnames). Informational footprint,
        # not a vulnerability — its own cluster; the judge rates it (usually low).
        return f"hostprofile|{ev.subject_value}", Category.EXPOSED_INFRASTRUCTURE, False, None

    if ev.kind in ("phone_risk", "phone_meta"):
        # What a phone number reveals / how exposed it is (carrier, line type, spam/
        # fraud reputation). One "your phone number" story per subject.
        raw = ev.signals[0].raw if ev.signals else {}
        force = bool(raw.get("recent_abuse") or raw.get("leaked") or raw.get("spammer"))
        reason = "phone number flagged for abuse / found in leaks" if force else None
        return (f"phone|{ev.subject_value}", Category.ACCOUNT_METADATA, force, reason)

    # Unknown kind: own cluster, let the triage net decide.
    return f"{ev.kind}|{ev.subject_value}|{ev.locator}", Category.BREACH_MEMBERSHIP, False, None


def cluster_evidence(evidence: list[Evidence]) -> list[EvidenceCluster]:
    buckets: "OrderedDict[str, dict]" = OrderedDict()
    for ev in evidence:
        sig, category, force, reason = _classify(ev)
        b = buckets.get(sig)
        if b is None:
            b = {
                "category": category,
                "subject_value": ev.subject_value,
                "subject_type": ev.subject_type,
                "kind": ev.kind,
                "members": [],
                "locators": [],
                "force": False,
                "reason": None,
            }
            buckets[sig] = b
        b["members"].append(ev)
        if ev.locator not in b["locators"]:
            b["locators"].append(ev.locator)
        if force:
            b["force"] = True
            b["reason"] = b["reason"] or reason

    clusters: list[EvidenceCluster] = []
    for sig, b in buckets.items():
        clusters.append(
            EvidenceCluster(
                signature=sig,
                category_hint=b["category"],
                subject_value=b["subject_value"],
                subject_type=b["subject_type"],
                kind=b["kind"],
                members=b["members"],
                member_locators=b["locators"],
                force_escalate=b["force"],
                escalate_reason=b["reason"],
            )
        )
    return clusters
