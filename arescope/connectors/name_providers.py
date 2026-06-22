"""Name → data-broker / people-search provider adapters.

There is no clean free API for "is this person listed on broker sites" (TOOLS.md /
DEEP_SEARCH_PLAN.md): the options are a paid people-search aggregator or fragile
broker scraping. So the name connector is **provider-agnostic and config-gated** —
this module defines the adapter contract and one generic REST adapter you point at
your chosen provider (or a thin shim you host). No provider lock-in; absent config
=> no provider => the connector is unavailable => honest coverage gap.

Two tiers, gated by ownership (the self-audit hard rule, CLAUDE.md):
  * **normal** (name only): listing EXISTENCE per broker + the opt-out link. This is
    the legitimate self-audit use — surface your own listing so it can be removed.
    No address / relatives / age (that would be a dossier of a possibly-arbitrary
    person).
  * **extended** (name + ownership-verified via a linked email): the full listing
    detail, used to build the richer identity graph. Gated; built next
    (docs/OWNERSHIP_VERIFICATION.md). The `extended` flag threads through here so the
    seam exists, but the connector keeps it off until that gate lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx

from arescope.config import Settings


@dataclass
class BrokerListing:
    """One people-search/broker site that lists the searched name."""

    broker: str                      # display name, e.g. "Spokeo"
    broker_domain: str               # e.g. "spokeo.com" — opt-out lookup + graph slug
    listing_url: str | None = None   # the public listing page (if the provider gives one)
    opt_out_url: str | None = None   # where the user removes themselves
    match_confidence: float | None = None  # 0..1 if the provider scores name matches
    # Dossier detail (address/relatives/age). ONLY populated on the extended tier and
    # ONLY surfaced when ownership is verified — never in the normal name-only output.
    extended: dict = field(default_factory=dict)


@runtime_checkable
class NameProvider(Protocol):
    name: str

    def available(self, cfg: Settings) -> bool: ...

    def search(self, full_name: str, cfg: Settings, *, extended: bool = False) -> list[BrokerListing]: ...


class GenericRestNameProvider:
    """Config-gated REST adapter — works against any provider that speaks this contract.

    Request:  POST {name_search_api_url}
              Authorization: Bearer {name_search_api_key}
              JSON body: {"name": "<full name>", "extended": <bool>}

    Response (JSON): {"listings": [
        {"broker": "Spokeo", "domain": "spokeo.com",
         "listing_url": "https://…", "opt_out_url": "https://…",
         "match_confidence": 0.0-1.0,
         "details": { … dossier fields … }   # echoed only when extended was requested
        }, …]}

    Most real providers won't match this exact shape — host a small shim that maps
    your provider's response into it (that's the "wire a concrete API when you pick/
    pay" step). Unknown/extra fields are ignored.
    """

    name = "brokers"

    def available(self, cfg: Settings) -> bool:
        return bool(cfg.name_search_api_url and cfg.name_search_api_key)

    def search(self, full_name: str, cfg: Settings, *, extended: bool = False) -> list[BrokerListing]:
        resp = httpx.post(
            cfg.name_search_api_url,
            headers={
                "authorization": f"Bearer {cfg.name_search_api_key}",
                "user-agent": "arescope-self-audit",
            },
            json={"name": full_name, "extended": bool(extended)},
            timeout=30,
        )
        resp.raise_for_status()
        out: list[BrokerListing] = []
        for row in (resp.json() or {}).get("listings", []):
            domain = (row.get("domain") or "").strip().lower()
            broker = row.get("broker") or domain
            if not (domain or broker):
                continue
            out.append(
                BrokerListing(
                    broker=broker or domain,
                    broker_domain=domain or broker,
                    listing_url=row.get("listing_url"),
                    opt_out_url=row.get("opt_out_url"),
                    match_confidence=row.get("match_confidence"),
                    # Hold dossier detail back unless this was an extended (gated) query.
                    extended=(row.get("details") or {}) if extended else {},
                )
            )
        return out


# Registered providers. Add concrete adapters here; the first available one wins.
_PROVIDERS: list[NameProvider] = [GenericRestNameProvider()]


def resolve_name_provider(cfg: Settings) -> NameProvider | None:
    """The configured name provider, or None (=> connector unavailable => coverage gap)."""
    for provider in _PROVIDERS:
        if provider.available(cfg):
            return provider
    return None
