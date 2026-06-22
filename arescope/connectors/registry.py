"""Connector registry. Add a connector here and the orchestrator routes to it."""

from __future__ import annotations

from arescope.config import Settings
from arescope.connectors.base import Connector
from arescope.connectors.hibp import HIBPConnector
from arescope.connectors.holehe import HoleheConnector
from arescope.connectors.hudsonrock import HudsonRockConnector
from arescope.connectors.maigret import MaigretConnector
from arescope.connectors.name import NameConnector
from arescope.connectors.shodan import ShodanConnector

REGISTRY: list[Connector] = [
    HIBPConnector(),
    HudsonRockConnector(),
    HoleheConnector(),
    MaigretConnector(),
    ShodanConnector(),
    NameConnector(),
]


def available_connectors(cfg: Settings) -> list[Connector]:
    return [c for c in REGISTRY if c.available(cfg)]
