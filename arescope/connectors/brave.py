"""Brave Search — where a name surfaces across the public web (#5 identity, admin).

Consumes: name. Admin-only (broad web search of a person is the line the self-audit
hard rule guards on the user tier — EXTENDED_SEARCH_SCOPE.md). Key-gated on
ARESCOPE_BRAVE_API_KEY (Brave's metered tier, $5 free credits/mo). Brave operates
its own index, so unlike SERP-scrapers it carries no Google-scraping legal exposure.

Surfaces the "vanity search": news, articles, public records, profile pages and
social mentions tied to the name — the universal footprint everyone has, regardless
of whether they use developer-y platforms.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from arescope.config import Settings
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class BraveConnector(Connector):
    name = "brave"
    consumes = {InputType.NAME}
    admin_only = True

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.brave_api_key)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        headers = {
            "accept": "application/json",
            "accept-encoding": "gzip",
            "x-subscription-token": cfg.brave_api_key,
        }
        # Exact-phrase the name so we match the person, not the two words apart.
        params = {"q": f'"{value}"', "count": 10, "safesearch": "off"}
        try:
            resp = httpx.get(_ENDPOINT, headers=headers, params=params, timeout=20)
        except httpx.HTTPError as e:
            raise ConnectorGap(f"brave request failed: {e}") from e

        if resp.status_code == 401:
            raise ConnectorGap("brave rejected the API key (401)")
        if resp.status_code == 429:
            raise ConnectorGap("brave rate-limited / out of credits (429)")
        if resp.status_code >= 400:
            raise ConnectorGap(f"brave returned {resp.status_code}")

        results = ((resp.json() or {}).get("web") or {}).get("results") or []
        signals: list[Signal] = []
        for r in results:
            url = r.get("url")
            if not url:
                continue
            domain = (urlparse(url).netloc or "").lower()
            signals.append(
                Signal(
                    source=self.name,
                    kind="web_mention",
                    locator=url,
                    subject_value=value,
                    subject_type=InputType.NAME,
                    raw={
                        "title": r.get("title"),
                        "url": url,
                        "domain": domain[4:] if domain.startswith("www.") else domain,
                        "description": r.get("description"),
                        "age": r.get("age"),
                    },
                )
            )
        return signals
