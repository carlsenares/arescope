"""Connector registry. Add a connector here and the orchestrator routes to it."""

from __future__ import annotations

from aresis.config import Settings
from aresis.connectors.base import Connector
from aresis.connectors.hibp import HIBPConnector
from aresis.connectors.holehe import HoleheConnector
from aresis.connectors.hudsonrock import HudsonRockConnector
from aresis.connectors.maigret import MaigretConnector
from aresis.connectors.shodan import ShodanConnector

REGISTRY: list[Connector] = [
    HIBPConnector(),
    HudsonRockConnector(),
    HoleheConnector(),
    MaigretConnector(),
    ShodanConnector(),
]


def available_connectors(cfg: Settings) -> list[Connector]:
    return [c for c in REGISTRY if c.available(cfg)]
