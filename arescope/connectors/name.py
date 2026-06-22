"""Name → data-broker / people-search listings (#7).

Consumes: name. Provider-agnostic + config-gated (see name_providers.py): absent
config => no provider => not available => coverage gap (never a failure).

Emits one Signal per broker that lists the name. The "normal" (name-only) tier
carries listing EXISTENCE + the opt-out link, which feeds the T1 removal artifact —
the legitimate self-audit use ("here's your listing, here's how to remove it"). The
full dossier is the gated "extended" tier (name + verified email), built next; the
`name_extended` flag threads the seam through but stays off until that gate lands.
"""

from __future__ import annotations

import httpx

from arescope.config import Settings
from arescope.connectors.base import Connector, ConnectorGap, ConnectorUnavailable
from arescope.connectors.name_providers import resolve_name_provider
from arescope.schemas import InputType, Signal


class NameConnector(Connector):
    name = "brokers"
    consumes = {InputType.NAME}

    def available(self, cfg: Settings) -> bool:
        return resolve_name_provider(cfg) is not None

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        provider = resolve_name_provider(cfg)
        if provider is None:
            raise ConnectorUnavailable("no name-search provider configured")

        # Extended (dossier) tier only when ownership is verified for this name — gated
        # by the per-scan flag the service sets; default off => listing-existence only.
        extended = bool(getattr(cfg, "name_extended", False))
        # Did the provider actually confirm THIS name is listed (paid lookup), or only
        # enumerate the removal catalog (free fallback)? Threads into every signal so the
        # judge + report never imply coverage we didn't have (CLAUDE.md degrade-gracefully).
        confirmed = bool(getattr(provider, "confirms_listings", True))
        try:
            listings = provider.search(value, cfg, extended=extended)
        except httpx.HTTPError as e:  # network/transport/status
            raise ConnectorGap(f"name search failed: {e}") from e

        signals: list[Signal] = []
        for li in listings:
            signals.append(
                Signal(
                    source=self.name,
                    kind="broker_listing",
                    locator=li.broker_domain,
                    subject_value=value,
                    subject_type=InputType.NAME,
                    raw={
                        "broker": li.broker,
                        "domain": li.broker_domain,
                        "listing_url": li.listing_url,
                        "opt_out_url": li.opt_out_url,
                        "match_confidence": li.match_confidence,
                        # False => "you may be listed here, opt out to be safe", not a
                        # confirmed hit. The report and the judge key off this.
                        "confirmed": confirmed,
                        "ca_registered": li.ca_registered,
                        # the dossier exists but is gated unless extended was requested
                        "has_details": bool(li.extended),
                        **({"details": li.extended} if li.extended else {}),
                    },
                )
            )
        return signals
