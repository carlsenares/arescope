"""IP enrichment connectors (#6) — geo/network + reputation for an IP you own.

All emit a `host_profile` Signal keyed on the IP (same kind Shodan uses), so they
MERGE with Shodan into one corroborated "your address" cluster rather than four
separate findings. Each is key-gated and degrades to a coverage gap on any error.

- IPinfo     — geo / ASN / hosting-vs-residential (the "what your IP gives away").
- AbuseIPDB  — abuse-report reputation (is your IP on blocklists / flagged).
- VirusTotal — malicious-engine reputation. NON-COMMERCIAL licence => admin_only.
- Censys     — host/service exposure cross-check (Censys Platform PAT, Bearer auth).
"""

from __future__ import annotations

import httpx

from arescope.config import Settings
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal


def _host_signal(source: str, ip: str, raw: dict) -> Signal:
    return Signal(
        source=source, kind="host_profile", locator=ip,
        subject_value=ip, subject_type=InputType.IP, raw=raw,
    )


class IPinfoConnector(Connector):
    name = "ipinfo"
    consumes = {InputType.IP}

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.ipinfo_token)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            resp = httpx.get(
                f"https://ipinfo.io/{value}/json",
                params={"token": cfg.ipinfo_token}, timeout=15,
            )
        except httpx.HTTPError as e:
            raise ConnectorGap(f"ipinfo request failed: {e}") from e
        if resp.status_code == 401:
            raise ConnectorGap("ipinfo rejected the token (401)")
        if resp.status_code == 429:
            raise ConnectorGap("ipinfo rate-limited (429)")
        if resp.status_code != 200:
            raise ConnectorGap(f"ipinfo unexpected status {resp.status_code}")
        d = resp.json() or {}
        loc = ", ".join(p for p in (d.get("city"), d.get("region"), d.get("country")) if p)
        return [_host_signal("ipinfo", value, {
            "location": loc or d.get("country"),
            "city": d.get("city"), "region": d.get("region"),
            "country_code": d.get("country"), "postal": d.get("postal"),
            "org": d.get("org"), "isp": d.get("org"), "hostnames": [d.get("hostname")]
            if d.get("hostname") else None, "timezone": d.get("timezone"),
        })]


class AbuseIPDBConnector(Connector):
    name = "abuseipdb"
    consumes = {InputType.IP}

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.abuseipdb_api_key)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            resp = httpx.get(
                "https://api.abuseipdb.com/api/v2/check",
                params={"ipAddress": value, "maxAgeInDays": 90},
                headers={"Key": cfg.abuseipdb_api_key, "Accept": "application/json"},
                timeout=15,
            )
        except httpx.HTTPError as e:
            raise ConnectorGap(f"abuseipdb request failed: {e}") from e
        if resp.status_code == 401:
            raise ConnectorGap("abuseipdb rejected the API key (401)")
        if resp.status_code == 429:
            raise ConnectorGap("abuseipdb rate-limited (429)")
        if resp.status_code != 200:
            raise ConnectorGap(f"abuseipdb unexpected status {resp.status_code}")
        d = (resp.json() or {}).get("data") or {}
        return [_host_signal("abuseipdb", value, {
            "abuse_score": d.get("abuseConfidenceScore"),
            "total_reports": d.get("totalReports"),
            "usage_type": d.get("usageType"), "isp": d.get("isp"),
            "domains": [d.get("domain")] if d.get("domain") else None,
            "country_code": d.get("countryCode"), "is_tor": d.get("isTor"),
            "last_reported": d.get("lastReportedAt"),
        })]


class VirusTotalIPConnector(Connector):
    name = "virustotal"
    consumes = {InputType.IP}
    # Free-tier licence is NON-COMMERCIAL — never runs in a commercial build / for
    # the public tier. Admin-only keeps it on the self-audit side only.
    admin_only = True

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.virustotal_api_key)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            resp = httpx.get(
                f"https://www.virustotal.com/api/v3/ip_addresses/{value}",
                headers={"x-apikey": cfg.virustotal_api_key}, timeout=15,
            )
        except httpx.HTTPError as e:
            raise ConnectorGap(f"virustotal request failed: {e}") from e
        if resp.status_code == 401:
            raise ConnectorGap("virustotal rejected the API key (401)")
        if resp.status_code == 429:
            raise ConnectorGap("virustotal rate-limited (429)")
        if resp.status_code != 200:
            raise ConnectorGap(f"virustotal unexpected status {resp.status_code}")
        a = (((resp.json() or {}).get("data") or {}).get("attributes")) or {}
        stats = a.get("last_analysis_stats") or {}
        return [_host_signal("virustotal", value, {
            "malicious_engines": stats.get("malicious"),
            "suspicious_engines": stats.get("suspicious"),
            "reputation": a.get("reputation"), "org": a.get("as_owner"),
            "asn": a.get("asn"), "country_code": a.get("country"),
        })]


class CensysIPConnector(Connector):
    name = "censys"
    consumes = {InputType.IP}

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.censys_token)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        # Censys Platform host view (Bearer PAT). Endpoint shape may evolve; any
        # non-200 degrades to a coverage gap rather than failing the scan.
        try:
            resp = httpx.get(
                f"https://api.platform.censys.io/v3/global/asset/host/{value}",
                headers={"Authorization": f"Bearer {cfg.censys_token}",
                         "Accept": "application/json"},
                timeout=20,
            )
        except httpx.HTTPError as e:
            raise ConnectorGap(f"censys request failed: {e}") from e
        if resp.status_code in (401, 403):
            raise ConnectorGap(f"censys rejected the token ({resp.status_code})")
        if resp.status_code == 404:
            return []  # nothing indexed for this IP — clean
        if resp.status_code == 429:
            raise ConnectorGap("censys rate-limited (429)")
        if resp.status_code != 200:
            raise ConnectorGap(f"censys unexpected status {resp.status_code}")
        body = resp.json() or {}
        # Platform host view nests the asset under result.resource.
        host = ((body.get("result") or {}).get("resource")) or body.get("result") or body
        services = host.get("services") or []
        loc = host.get("location") or {}
        asys = host.get("autonomous_system") or {}
        ports = sorted({s.get("port") for s in services if s.get("port")})
        return [_host_signal("censys", value, {
            "location": ", ".join(p for p in (loc.get("city"), loc.get("country")) if p)
            or loc.get("country"),
            "country_code": loc.get("country_code"),
            "isp": asys.get("name") or asys.get("description"),
            "asn": asys.get("asn"),
            "open_ports": ports,
            "services": [f"{s.get('port')}/{s.get('service_name') or s.get('transport_protocol')}"
                         for s in services][:25],
        })]
