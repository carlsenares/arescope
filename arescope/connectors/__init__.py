"""Source connectors. Import the registry to discover available ones."""

from arescope.connectors.registry import REGISTRY, available_connectors

__all__ = ["REGISTRY", "available_connectors"]
