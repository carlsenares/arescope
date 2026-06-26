"""Camoufox stealth-browser foundation — the engine behind public-content extraction.

The identity map's hard problem is pulling PUBLIC content off walled/JS platforms
(Instagram/LinkedIn/Google) that block plain HTTP clients. Camoufox is an anti-detect
Firefox (C++-level fingerprint spoofing, sandboxed Playwright) that gets through where
httpx is blocked. This module is a thin, reusable wrapper so connectors don't each
re-learn how to launch it.

Design rules, consistent with the rest of the connector layer:
  * **Self-hosted + gated.** Camoufox is an optional `[browser]` extra and downloads a
    Firefox binary on first use. If it isn't installed we raise ConnectorGap — a clean
    coverage gap, never a crash (same contract as Sherlock/Maigret/EXIF).
  * **Admin/demo-first.** Logged-in scraping uses a stored browser session
    (`storage_state` JSON exported once by the founder). Shared credentials don't scale
    — they rate-limit/ban — so connectors built on this stay admin_only until the
    per-user-session model exists (GRAPH.md §0, EXTENDED_SEARCH_SCOPE.md).
  * **Fetch only, no navigation agent (yet).** v1 does request-style fetches through a
    real browser context (cookies + fingerprint apply). LLM-driven navigation is a
    later layer.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from arescope.connectors.base import ConnectorGap

_log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    status: int
    text: str

    def json(self) -> dict:
        try:
            return json.loads(self.text)
        except (ValueError, TypeError):
            return {}


@dataclass
class RenderResult:
    """A JS-rendered page: the final HTML plus any XHR/fetch response bodies that matched
    `capture_substr` (the data a single-page app loads after first paint)."""
    html: str
    captured: list[str]


def available() -> bool:
    """True if the Camoufox lib is importable (the binary is fetched lazily)."""
    try:
        import camoufox.sync_api  # noqa: F401
    except Exception:
        return False
    return True


def fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    storage_state_path: str | None = None,
    timeout_ms: int = 30000,
) -> FetchResult:
    """Fetch a URL through a stealth browser context and return (status, text).

    Uses the browser context's request API so the spoofed fingerprint, cookies and any
    loaded session apply — i.e. the server sees a real Firefox, not a scraper. Pass
    `storage_state_path` to a Playwright storage-state JSON to fetch the LOGGED-IN view
    (admin/demo only). Raises ConnectorGap on any failure so the scan degrades, never
    dies.
    """
    if not available():
        raise ConnectorGap("camoufox not installed (browser extra absent)")
    try:
        from camoufox.sync_api import Camoufox
    except Exception as e:  # pragma: no cover - exercised only when extra present
        raise ConnectorGap(f"camoufox import failed: {e}") from e

    # Warn (don't fail) when a session path is set but missing — otherwise an admin who
    # expected the logged-in view silently gets the logged-out one (CodeRabbit #1).
    state = None
    if storage_state_path:
        if os.path.exists(storage_state_path):
            state = storage_state_path
        else:
            _log.warning("storage_state_path %s not found; using logged-out view",
                         storage_state_path)
    try:
        with Camoufox(headless=True) as browser:
            context = browser.new_context(storage_state=state) if state else browser.new_context()
            try:
                resp = context.request.get(url, headers=headers or {}, timeout=timeout_ms)
                return FetchResult(status=resp.status, text=resp.text())
            finally:
                context.close()
    except ConnectorGap:
        raise
    except Exception as e:  # pragma: no cover - network/browser failures
        raise ConnectorGap(f"camoufox fetch failed: {e}") from e


# Google's EU consent interstitial blocks a logged-out render until accepted. Seeding the
# consent cookies skips it (same trick GHunt uses), so the page goes straight to content.
_GOOGLE_CONSENT_COOKIES = [
    {"name": "CONSENT", "value": "YES+cb.20220118-08-p0.fr+FX+510", "domain": ".google.com", "path": "/"},
    {"name": "SOCS", "value": "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg", "domain": ".google.com", "path": "/"},
]


def render(
    url: str,
    *,
    wait_selector: str | None = None,
    wait_ms: int = 4000,
    capture_substr: str | None = None,
    scroll_rounds: int = 0,
    consent_cookies: list[dict] | None = None,
    storage_state_path: str | None = None,
    timeout_ms: int = 30000,
) -> RenderResult:
    """Navigate to `url` in a real browser, run its JS, return the rendered HTML + any
    captured XHR bodies.

    Unlike `fetch` (request-only, no JS), this drives a page so a single-page app
    (Google Maps contributor reviews, …) actually loads its content. `capture_substr`
    records the bodies of network responses whose URL contains that substring — the
    internal RPC the app calls — which is usually a cleaner source than scraping the DOM.
    `scroll_rounds` pages a lazy-loading list. Raises ConnectorGap on any failure so the
    scan degrades, never dies.
    """
    if not available():
        raise ConnectorGap("camoufox not installed (browser extra absent)")
    try:
        from camoufox.sync_api import Camoufox
    except Exception as e:  # pragma: no cover - exercised only when extra present
        raise ConnectorGap(f"camoufox import failed: {e}") from e

    state = None
    if storage_state_path:
        if os.path.exists(storage_state_path):
            state = storage_state_path
        else:
            _log.warning("storage_state_path %s not found; using logged-out view",
                         storage_state_path)
    captured: list[str] = []
    try:
        with Camoufox(headless=True) as browser:
            context = browser.new_context(storage_state=state) if state else browser.new_context()
            try:
                if not state:
                    context.add_cookies(consent_cookies if consent_cookies is not None
                                        else _GOOGLE_CONSENT_COOKIES)
                page = context.new_page()
                if capture_substr:
                    def _on_response(resp):  # pragma: no cover - needs live browser
                        try:
                            if capture_substr in resp.url:
                                captured.append(resp.text())
                        except Exception:
                            pass
                    page.on("response", _on_response)
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                if wait_selector:
                    try:
                        page.wait_for_selector(wait_selector, timeout=wait_ms)
                    except Exception:
                        pass  # selector never appeared → caller degrades on empty html
                for _ in range(scroll_rounds):  # pragma: no cover - needs live browser
                    page.mouse.wheel(0, 4000)
                    page.wait_for_timeout(800)
                page.wait_for_timeout(wait_ms if not wait_selector else 600)
                return RenderResult(html=page.content(), captured=captured)
            finally:
                context.close()
    except ConnectorGap:
        raise
    except Exception as e:  # pragma: no cover - network/browser failures
        raise ConnectorGap(f"camoufox render failed: {e}") from e
