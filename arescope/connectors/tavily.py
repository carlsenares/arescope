"""Tavily — AI web search for a name (#5), the LLM-clean alternative to Brave.

Consumes: name. Admin-only (broad web search of a person is the line the self-audit
hard rule guards). Key-gated on ARESCOPE_TAVILY_API_KEY (free 1,000 searches/mo).
Emits `web_mention` Signals (same kind as Brave/urlscan) — for v1 we surface the
result links directly; the Sonnet "turn results into structured facts" step belongs
to the map Evaluate pass (docs/GRAPH.md §13a), not here.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from arescope.config import Settings
from arescope.connectors._webfilter import is_directory_noise
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_ENDPOINT = "https://api.tavily.com/search"


class TavilyConnector(Connector):
    name = "tavily"
    consumes = {InputType.NAME}
    admin_only = True

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.tavily_api_key)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            resp = httpx.post(_ENDPOINT, json={
                "api_key": cfg.tavily_api_key,
                "query": f'"{value}"',
                "max_results": 12,
                "search_depth": "basic",
            }, timeout=30)
        except httpx.HTTPError as e:
            raise ConnectorGap(f"tavily request failed: {e}") from e
        if resp.status_code in (401, 403):
            raise ConnectorGap(f"tavily rejected the key ({resp.status_code})")
        if resp.status_code == 429:
            raise ConnectorGap("tavily rate-limited / out of credits (429)")
        if resp.status_code != 200:
            raise ConnectorGap(f"tavily returned {resp.status_code}")

        signals: list[Signal] = []
        seen: set[str] = set()
        for r in (resp.json() or {}).get("results") or []:
            url = r.get("url")
            if not url:
                continue
            if is_directory_noise(url, r.get("title")):
                continue  # people-search aggregators / "N profiles named X" — not the owner
            domain = (urlparse(url).netloc or "").lower()
            domain = domain[4:] if domain.startswith("www.") else domain
            if domain in seen:
                continue
            seen.add(domain)
            signals.append(Signal(
                source=self.name, kind="web_mention", locator=url,
                subject_value=value, subject_type=InputType.NAME,
                raw={"title": r.get("title"), "url": url, "domain": domain,
                     "description": (r.get("content") or "")[:300],
                     "score": r.get("score")},
            ))
        return signals
