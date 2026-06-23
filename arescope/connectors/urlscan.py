"""urlscan.io — where an identifier appears in publicly scanned pages (#5/#8).

Consumes: email, username, name. Key-gated (ARESCOPE_URLSCAN_API_KEY, free tier).
Searches urlscan's index of scanned pages for the value and emits one `web_mention`
Signal per hit (same kind Brave uses), so the judge frames it as footprint/metadata.
Complements Brave (live web) with a different corpus (submitted page scans).
"""

from __future__ import annotations

import httpx

from arescope.config import Settings
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_API = "https://urlscan.io/api/v1/search/"


class UrlscanConnector(Connector):
    name = "urlscan"
    consumes = {InputType.EMAIL, InputType.USERNAME, InputType.NAME}

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.urlscan_api_key)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            resp = httpx.get(
                _API, params={"q": f'"{value}"', "size": 20},
                headers={"API-Key": cfg.urlscan_api_key, "Accept": "application/json"},
                timeout=20,
            )
        except httpx.HTTPError as e:
            raise ConnectorGap(f"urlscan request failed: {e}") from e
        if resp.status_code == 401:
            raise ConnectorGap("urlscan rejected the API key (401)")
        if resp.status_code == 429:
            raise ConnectorGap("urlscan rate-limited (429)")
        if resp.status_code != 200:
            raise ConnectorGap(f"urlscan unexpected status {resp.status_code}")

        signals: list[Signal] = []
        seen: set[str] = set()
        for r in (resp.json() or {}).get("results") or []:
            page = r.get("page") or {}
            url = page.get("url")
            domain = (page.get("domain") or "").lower()
            if not url or domain in seen:
                continue
            seen.add(domain)  # one mention per domain — avoid 20 hits from one site
            signals.append(
                Signal(
                    source=self.name, kind="web_mention", locator=url,
                    subject_value=value, subject_type=input_type,
                    raw={"title": page.get("title"), "url": url, "domain": domain,
                         "description": None, "seen_at": (r.get("task") or {}).get("time")},
                )
            )
        return signals
