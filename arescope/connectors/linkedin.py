"""LinkedIn extraction, fed by a profile URL discovered upstream (PDL).

LinkedIn has no usable public API and can't be reached from a bare handle, so this runs
as a **post-discovery enrichment pass** (service._enrich_linkedin): PDL surfaces the
`linkedin_url`, then we fetch that page's content — resolving the URL ONCE rather than
re-querying PDL per connector. Two paths, built to be compared side by side:

  * **Jina Reader** (r.jina.ai) — free, no key, no cookie: fetches the PUBLIC page as
    markdown. Shallow but robust and scalable. Runs for every tier (the regular path).
  * **Apify LinkedIn actor** — admin-only, credit-metered: deep profile (headline,
    company, location, photo, sometimes activity). The "wow" path.

Both degrade to a coverage gap and emit the same `account` + identity_attribute shapes
as the other social connectors, so they ride the existing graph/post-node rendering.
"""

from __future__ import annotations

import re

import httpx

from arescope.config import Settings
from arescope.connectors._identity import COMPANY, LOCATION, NAME, PHOTO, identity_signal
from arescope.connectors.base import ConnectorGap
from arescope.schemas import InputType, Signal

_JINA = "https://r.jina.ai/"
_APIFY_RUN = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"


def jina_available(cfg: Settings) -> bool:
    return cfg.jina_enabled


def apify_linkedin_available(cfg: Settings) -> bool:
    return bool(cfg.apify_token and cfg.apify_linkedin_actor)


def _account_signal(source: str, url: str, subject_value: str, subject_type: InputType, *,
                    display_name=None, description=None, posts=None) -> Signal:
    return Signal(
        source=source, kind="account", locator="linkedin.com",
        subject_value=subject_value, subject_type=subject_type,
        raw={"url": url, "domain": "linkedin.com", "display_name": display_name,
             "description": description, "recent_posts": posts or []},
    )


# --- Jina Reader (free public page → markdown) -------------------------------

def _parse_jina(markdown: str, url: str) -> dict:
    """Best-effort extract of a LinkedIn public page from Jina's markdown (testable).

    Jina prefixes a `Title:` line; LinkedIn titles look like
    "Jane Doe - Senior PM - Acme | LinkedIn". We pull a name + headline from it and keep
    a snippet so Opus Evaluate has the raw text. Extraction is intentionally shallow —
    the public page gives little — and never throws on odd input.
    """
    title = ""
    m = re.search(r"^Title:\s*(.+)$", markdown, re.MULTILINE)
    if m:
        title = m.group(1).strip()
    title = re.sub(r"\s*\|\s*LinkedIn\s*$", "", title).strip()
    name, headline = title, None
    if " - " in title:
        name, _, headline = title.partition(" - ")
        name, headline = name.strip(), headline.strip() or None
    # drop the Jina header block, keep a content snippet for inference
    body = re.sub(r"^(Title|URL Source|Published Time|Markdown Content):.*$", "",
                  markdown, flags=re.MULTILINE).strip()
    return {"name": name or None, "headline": headline, "snippet": body[:600] or None}


def fetch_via_jina(url: str, cfg: Settings, subject_value: str,
                   subject_type: InputType) -> list[Signal]:
    headers = {"Accept": "text/plain", "X-Return-Format": "markdown"}
    if cfg.jina_api_key:
        headers["Authorization"] = f"Bearer {cfg.jina_api_key}"
    try:
        resp = httpx.get(_JINA + url, headers=headers, timeout=30,
                         follow_redirects=True)
    except httpx.HTTPError as e:
        raise ConnectorGap(f"jina request failed: {e}") from e
    if resp.status_code == 429:
        raise ConnectorGap("jina rate-limited (429)")
    if resp.status_code != 200:
        raise ConnectorGap(f"jina returned {resp.status_code}")

    p = _parse_jina(resp.text or "", url)
    sigs: list[Signal] = [_account_signal(
        "linkedin_jina", url, subject_value, subject_type,
        display_name=p["name"], description=p["headline"] or p["snippet"])]
    if p["name"]:
        sigs.append(identity_signal(
            source="linkedin_jina", attribute=NAME, value=p["name"],
            subject_value=subject_value, subject_type=subject_type, platform="linkedin"))
    return sigs


# --- Apify LinkedIn actor (deep profile, admin-only) -------------------------

def _parse_apify_linkedin(item: dict, url: str) -> dict:
    """Pure extract from a LinkedIn profile actor item (field names vary by actor)."""
    name = item.get("fullName") or " ".join(
        filter(None, [item.get("firstName"), item.get("lastName")])) or None
    location = item.get("addressWithCountry") or item.get("location") or item.get("geoLocationName")
    company = item.get("companyName") or item.get("company")
    photo = item.get("profilePic") or item.get("profilePicHighQuality") or item.get("profilePicture")
    return {
        "name": name,
        "headline": item.get("headline") or item.get("occupation"),
        "location": location,
        "company": company,
        "photo": photo,
    }


def fetch_via_apify(url: str, cfg: Settings, subject_value: str,
                    subject_type: InputType) -> list[Signal]:
    actor = cfg.apify_linkedin_actor.replace("/", "~")
    try:
        resp = httpx.post(
            _APIFY_RUN.format(actor=actor),
            params={"token": cfg.apify_token, "timeout": 120, "maxItems": 1},
            json={"profileUrls": [url]}, timeout=150,
        )
    except httpx.HTTPError as e:
        raise ConnectorGap(f"apify linkedin request failed: {e}") from e
    if resp.status_code in (401, 403):
        raise ConnectorGap(f"apify rejected the token ({resp.status_code})")
    if resp.status_code == 402:
        raise ConnectorGap("apify out of credits (402)")
    if resp.status_code not in (200, 201):
        raise ConnectorGap(f"apify linkedin returned {resp.status_code}")

    items = resp.json() or []
    it = items[0] if isinstance(items, list) and items else (items if isinstance(items, dict) else {})
    if not it or it.get("error"):
        return []

    p = _parse_apify_linkedin(it, url)
    sigs: list[Signal] = [_account_signal(
        "linkedin_apify", url, subject_value, subject_type,
        display_name=p["name"], description=p["headline"])]
    if p["name"]:
        sigs.append(identity_signal(
            source="linkedin_apify", attribute=NAME, value=p["name"],
            subject_value=subject_value, subject_type=subject_type, platform="linkedin"))
    if p["location"]:
        sigs.append(identity_signal(
            source="linkedin_apify", attribute=LOCATION, value=str(p["location"]),
            subject_value=subject_value, subject_type=subject_type, platform="linkedin"))
    if p["company"]:
        sigs.append(identity_signal(
            source="linkedin_apify", attribute=COMPANY, value=str(p["company"]),
            subject_value=subject_value, subject_type=subject_type, platform="linkedin"))
    if p["photo"]:
        sigs.append(identity_signal(
            source="linkedin_apify", attribute=PHOTO, value=str(p["photo"]),
            subject_value=subject_value, subject_type=subject_type, platform="linkedin"))
    return sigs
