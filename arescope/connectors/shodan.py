"""Shodan — exposed services/ports + CVEs on an IP you own (#6), plus what the IP
itself reveals (geolocation, ISP/ASN, hostnames).

Consumes: ip. Requires: ARESCOPE_SHODAN_API_KEY. The free API key (any Shodan
account) works for host lookups; absent/over-quota => coverage gap, not failure.

Emits one Signal per exposed service (port/transport) carrying product/version,
CPE, and any CVEs — the judge turns default-cred/known-CVE admin services into
Critical, sensitive services into High, banners into Medium. Also emits one
`host_profile` Signal: the approximate location, network/ISP, and reachable
hostnames the IP exposes — so the user sees what their address gives away (an
honest picture; behind NAT this is the gateway, not every device on the LAN)."""

from __future__ import annotations

import httpx

from arescope.config import Settings
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_API = "https://api.shodan.io"


class ShodanConnector(Connector):
    name = "shodan"
    consumes = {InputType.IP}

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.shodan_api_key)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            resp = httpx.get(
                f"{_API}/shodan/host/{value}",
                params={"key": cfg.shodan_api_key},
                timeout=20,
            )
        except httpx.HTTPError as e:
            raise ConnectorGap(f"shodan request failed: {e}") from e

        if resp.status_code == 404:
            return []  # nothing indexed for this IP — clean
        if resp.status_code == 401:
            raise ConnectorGap("shodan rejected the API key (401)")
        if resp.status_code == 403:
            raise ConnectorGap("shodan access denied / plan lacks host lookup (403)")
        if resp.status_code == 429:
            raise ConnectorGap("shodan rate-limited (429)")
        if resp.status_code != 200:
            raise ConnectorGap(f"shodan unexpected status {resp.status_code}")

        host = resp.json()
        hostnames = host.get("hostnames")
        org = host.get("org")

        signals: list[Signal] = []

        # Host-profile signal: what the IP itself gives away (location + network).
        loc_parts = [host.get("city"), host.get("region_code"), host.get("country_name")]
        location = ", ".join(p for p in loc_parts if p) or host.get("country_name") or "unknown"
        signals.append(
            Signal(
                source=self.name,
                kind="host_profile",
                locator=value,
                subject_value=value,
                subject_type=InputType.IP,
                raw={
                    "location": location,
                    "city": host.get("city"),
                    "region": host.get("region_code"),
                    "country": host.get("country_name"),
                    "country_code": host.get("country_code"),
                    "latitude": host.get("latitude"),
                    "longitude": host.get("longitude"),
                    "isp": host.get("isp"),
                    "org": org,
                    "asn": host.get("asn"),
                    "os": host.get("os"),
                    "hostnames": hostnames,
                    "domains": host.get("domains"),
                    "open_ports": host.get("ports"),
                    "tags": host.get("tags"),
                    "vulns": list((host.get("vulns") or [])),
                    "last_update": host.get("last_update"),
                },
            )
        )

        for service in host.get("data", []):
            port = service.get("port")
            transport = service.get("transport", "tcp")
            vulns = list((service.get("vulns") or {}).keys())
            signals.append(
                Signal(
                    source=self.name,
                    kind="exposed_service",
                    locator=f"{port}/{transport}",
                    subject_value=value,
                    subject_type=InputType.IP,
                    raw={
                        "port": port,
                        "transport": transport,
                        "product": service.get("product"),
                        "version": service.get("version"),
                        "cpe": service.get("cpe"),
                        "module": (service.get("_shodan") or {}).get("module"),
                        "vulns": vulns,
                        "hostnames": hostnames,
                        "org": org,
                    },
                )
            )
        return signals
