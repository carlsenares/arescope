"""Connector registry. Add a connector here and the orchestrator routes to it."""

from __future__ import annotations

from arescope.config import Settings
from arescope.connectors.base import Connector
from arescope.connectors.brave import BraveConnector
from arescope.connectors.ghunt import GHuntConnector
from arescope.connectors.github import GitHubConnector
from arescope.connectors.apify import ApifyConnector
from arescope.connectors.bluesky import BlueskyConnector
from arescope.connectors.exif import ExifConnector
from arescope.connectors.gravatar import GravatarConnector
from arescope.connectors.hibp import HIBPConnector
from arescope.connectors.holehe import HoleheConnector
from arescope.connectors.hudsonrock import HudsonRockConnector
from arescope.connectors.instagram_web import InstagramWebConnector
from arescope.connectors.intelx import IntelXConnector
from arescope.connectors.ip_sources import (
    AbuseIPDBConnector,
    CensysIPConnector,
    IPinfoConnector,
    VirusTotalIPConnector,
)
from arescope.connectors.leakcheck import LeakCheckConnector
from arescope.connectors.maigret import MaigretConnector
from arescope.connectors.name import NameConnector
from arescope.connectors.phone_sources import IPQSPhoneConnector, NumVerifyConnector
from arescope.connectors.phone_tools import IgnorantConnector, PhoneInfogaConnector
from arescope.connectors.reddit import RedditConnector
from arescope.connectors.sherlock import SherlockConnector
from arescope.connectors.shodan import ShodanConnector
from arescope.connectors.tavily import TavilyConnector
from arescope.connectors.pdl import PDLConnector
from arescope.connectors.urlscan import UrlscanConnector

REGISTRY: list[Connector] = [
    HIBPConnector(),
    LeakCheckConnector(),
    HudsonRockConnector(),
    HoleheConnector(),
    PDLConnector(),
    MaigretConnector(),
    SherlockConnector(),
    BlueskyConnector(),
    ExifConnector(),
    ShodanConnector(),
    IPinfoConnector(),
    AbuseIPDBConnector(),
    CensysIPConnector(),
    VirusTotalIPConnector(),
    NameConnector(),
    GitHubConnector(),
    GravatarConnector(),
    RedditConnector(),
    GHuntConnector(),
    BraveConnector(),
    TavilyConnector(),
    ApifyConnector(),
    InstagramWebConnector(),
    UrlscanConnector(),
    IntelXConnector(),
    IPQSPhoneConnector(),
    NumVerifyConnector(),
    IgnorantConnector(),
    PhoneInfogaConnector(),
]


def available_connectors(cfg: Settings) -> list[Connector]:
    return [c for c in REGISTRY if c.available(cfg)]
