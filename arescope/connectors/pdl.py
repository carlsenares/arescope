"""People Data Labs — person enrichment from an email (#5 identity).

Consumes: email. Key-gated (ARESCOPE_PDL_API_KEY; free 100/mo, then PAYG ~$0.01).
From a single email PDL can return the person's real name, location, employer/role,
and linked social profiles (LinkedIn/Twitter/GitHub/…). We emit those as identity
attributes (name/location/company → map nodes) + `account` signals for each linked
profile, so one email fans out into a labelled cluster. Enrichment is keyed to the
owned email (not a fuzzy name search), so it stays self-audit-aligned.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from arescope.config import Settings
from arescope.connectors._identity import identity_signal
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_ENDPOINT = "https://api.peopledatalabs.com/v5/person/enrich"


class PDLConnector(Connector):
    name = "pdl"
    consumes = {InputType.EMAIL}

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.pdl_api_key)

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        try:
            resp = httpx.get(_ENDPOINT, params={"email": value, "min_likelihood": 6},
                             headers={"X-Api-Key": cfg.pdl_api_key}, timeout=20)
        except httpx.HTTPError as e:
            raise ConnectorGap(f"pdl request failed: {e}") from e
        if resp.status_code == 404:
            return []  # no confident match — clean
        if resp.status_code in (401, 403):
            raise ConnectorGap(f"pdl rejected the key ({resp.status_code})")
        if resp.status_code == 429:
            raise ConnectorGap("pdl rate-limited / quota exhausted (429)")
        if resp.status_code != 200:
            raise ConnectorGap(f"pdl returned {resp.status_code}")

        data = (resp.json() or {}).get("data") or {}
        signals: list[Signal] = []

        def attr(attribute, val, **meta):
            if val:
                signals.append(identity_signal(
                    source=self.name, attribute=attribute, value=str(val),
                    subject_value=value, subject_type=InputType.EMAIL,
                    platform="people data labs", meta=meta or None))

        attr("name", data.get("full_name"))
        attr("location", data.get("location_name"))
        if data.get("job_company_name"):
            attr("company", data["job_company_name"],
                 title=data.get("job_title"))

        # Linked social/professional profiles -> account nodes.
        urls: set[str] = set()
        for key in ("linkedin_url", "twitter_url", "github_url", "facebook_url"):
            if data.get(key):
                urls.add(str(data[key]))
        for p in (data.get("profiles") or []):
            if isinstance(p, dict) and p.get("url"):
                urls.add(str(p["url"]))
        for u in list(urls)[:25]:
            url = u if u.startswith("http") else f"https://{u}"
            domain = (urlparse(url).netloc or "").lower()
            signals.append(Signal(
                source=self.name, kind="account", locator=domain or url,
                subject_value=value, subject_type=InputType.EMAIL,
                raw={"url": url, "domain": domain.removeprefix("www.")},
            ))
        return signals
