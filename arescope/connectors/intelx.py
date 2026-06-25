"""IntelX (Intelligence X) — leaks, pastes, leaked documents, darkweb mentions (#1, #8).

Consumes: email, username, name, phone, IP. Requires ARESCOPE_INTELX_API_KEY.
**admin_only** — broad leak/paste/darkweb search crosses the self-audit line on the
user tier (EXTENDED_SEARCH_SCOPE.md); it only runs for admins until the per-input
ownership gate is built.

IntelX search is two-phase (see https://github.com/IntelligenceX/SDK): POST a term to
`/intelligent/search` to get a search id, then GET `/intelligent/search/result` to drain
records. Each record is a stored item (a leak/paste/document) that matched the term — we
emit one `web_mention` Signal per record (same kind the clustering layer already routes
to ACCOUNT_METADATA), carrying the item name, bucket, media type and date. We do NOT
download item contents — only the catalog metadata, so this stays a "where you appear"
signal, not a data warehouse.

Free-tier accounts use host `https://free.intelx.io` and are credit-capped (e.g. 50
`/intelligent/search`), so the host is config-driven (`ARESCOPE_INTELX_BASE_URL`) and the
connector is admin_only to conserve the budget. A wrong host/tier surfaces as a clean
401 coverage gap, never a crash.
"""

from __future__ import annotations

import time

import httpx

from arescope.config import Settings
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_MAX_RESULTS = 50
# How long to wait for the async search to populate (status 3 = "no results yet").
_POLL_TRIES = 4
_POLL_SLEEP = 1.0

# IntelX media type id -> human label (subset; unknowns fall back to the number).
_MEDIA = {
    0: "unknown", 1: "paste", 2: "paste-user", 3: "forum", 4: "forum-board",
    5: "forum-thread", 6: "forum-post", 7: "forum-user", 9: "leak", 13: "tweet",
    15: "text", 16: "PDF", 17: "Word doc", 18: "spreadsheet", 23: "archive",
    24: "document", 0x1000: "leak",
}


class IntelXConnector(Connector):
    name = "intelx"
    consumes = {InputType.EMAIL, InputType.USERNAME, InputType.NAME,
                InputType.PHONE, InputType.IP}
    admin_only = True

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.intelx_api_key)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        headers = {"x-key": cfg.intelx_api_key, "User-Agent": "arescope"}
        base = (cfg.intelx_base_url or "https://2.intelx.io").rstrip("/")
        # Phase 1: open a search, get its id.
        try:
            resp = httpx.post(
                f"{base}/intelligent/search",
                headers=headers,
                json={
                    "term": value, "buckets": [], "lookuplevel": 0,
                    "maxresults": _MAX_RESULTS, "timeout": 0,
                    "datefrom": "", "dateto": "", "sort": 2, "media": 0,
                    "terminate": [],
                },
                timeout=20,
            )
        except httpx.HTTPError as e:
            raise ConnectorGap(f"intelx search failed: {e}") from e
        if resp.status_code in (401, 402):
            raise ConnectorGap("intelx rejected the key / tier (401-402)")
        if resp.status_code == 429:
            raise ConnectorGap("intelx rate-limited (429)")
        if resp.status_code != 200:
            raise ConnectorGap(f"intelx search returned {resp.status_code}")
        search_id = (resp.json() or {}).get("id")
        if not search_id:
            return []  # invalid term / nothing to search

        # Phase 2: drain results (status 0 = ok+more, 1 = done, 2 = no id, 3 = not ready).
        records: list[dict] = []
        for _ in range(_POLL_TRIES):
            try:
                r = httpx.get(
                    f"{base}/intelligent/search/result",
                    headers=headers,
                    params={"id": search_id, "limit": _MAX_RESULTS, "previewlines": 0},
                    timeout=20,
                )
            except httpx.HTTPError as e:
                raise ConnectorGap(f"intelx result fetch failed: {e}") from e
            if r.status_code != 200:
                raise ConnectorGap(f"intelx result returned {r.status_code}")
            body = r.json() or {}
            records.extend(body.get("records") or [])
            status = body.get("status")
            if status in (0, 1) and records:  # got results
                break
            if status == 1:  # done, none found
                break
            if status == 3:  # still gathering — wait and re-poll
                time.sleep(_POLL_SLEEP)
                continue
            break

        signals: list[Signal] = []
        for rec in records[:_MAX_RESULTS]:
            media = _MEDIA.get(rec.get("media"), str(rec.get("media", "")))
            name = rec.get("name") or rec.get("description") or "Untitled item"
            sysid = rec.get("systemid")
            signals.append(
                Signal(
                    source=self.name,
                    kind="web_mention",
                    locator=str(sysid or name),
                    subject_value=value,
                    subject_type=input_type,
                    raw={
                        "title": name,
                        "bucket": rec.get("bucket"),
                        "media": media,
                        "date": rec.get("date") or rec.get("added"),
                        "url": f"https://intelx.io/?did={sysid}" if sysid else None,
                        "source_label": "Intelligence X",
                    },
                )
            )
        return signals
