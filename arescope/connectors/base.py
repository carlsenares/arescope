"""Connector contract (TOOLS.md §Connector contract).

A connector declares the input types it consumes, whether it's available under
the current config, and runs a query to emit Signals. The cardinal rule
(ARCHITECTURE.md §4.5): a missing key / rate-limit / block must raise
ConnectorUnavailable or ConnectorGap — never crash the scan. The orchestrator
turns those into a coverage gap in the report.
"""

from __future__ import annotations

import abc

from arescope.config import Settings
from arescope.schemas import InputType, Signal


class ConnectorUnavailable(Exception):
    """Raised by available()/run() when the connector can't run (no key, disabled)."""


class ConnectorGap(Exception):
    """Raised mid-run when coverage is partial (rate-limited, blocked, source down)."""


class Connector(abc.ABC):
    name: str
    consumes: set[InputType]
    # Admin-only sources (broad web search, locked-platform scraping, reverse face)
    # cross the line the self-audit hard rule guards on the user tier. The service
    # drops these for non-admins (EXTENDED_SEARCH_SCOPE.md). Default False = both tiers.
    admin_only: bool = False

    @abc.abstractmethod
    def available(self, cfg: Settings) -> bool:
        """True if key present + enabled. False => logged as 'skipped: not configured'."""

    @abc.abstractmethod
    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        """Query the source for one identifier. May raise ConnectorGap (logged)."""
