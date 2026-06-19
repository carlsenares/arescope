"""Shodan — exposed services/ports + CVEs on an IP you own (#6).

Consumes: ip. Requires: ARESIS_SHODAN_API_KEY. The free API key (any Shodan
account) works for host lookups; absent/over-quota => coverage gap, not failure.

Emits one Signal per exposed service (port/transport), carrying product/version,
CPE, and any CVEs Shodan attached — the judge turns default-cred/known-CVE admin
services into Critical, sensitive services into High, banners into Medium.
"""

from __future__ import annotations

import httpx

from aresis.config import Settings
from aresis.connectors.base import Connector, ConnectorGap
from aresis.schemas import InputType, Signal

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
