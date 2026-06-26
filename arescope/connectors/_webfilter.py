"""Drop people-directory / aggregator pages from name web-search results.

A search for a person's name surfaces real pages about them AND generic directory
pages that list MANY people of that name ("50+ profiles named X") — noise that isn't
about the owner. The web-search connectors (Brave, Tavily) call `is_directory_noise()`
to skip those before they reach storage, the map, or the Evaluate digest.

People-search/broker domains are dropped from *mentions* on purpose: they still surface
as `broker_listing` nodes (actionable, with an opt-out), so removing the redundant
web-mention only cuts noise, never coverage.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Aggregator / people-search domains that index many people, never a person's own page.
_DIRECTORY_DOMAINS = {
    "spokeo.com", "whitepages.com", "beenverified.com", "intelius.com",
    "truthfinder.com", "instantcheckmate.com", "peoplefinders.com", "mylife.com",
    "radaris.com", "fastpeoplesearch.com", "thatsthem.com", "zabasearch.com",
    "peoplesearchnow.com", "clustrmaps.com", "rocketreach.co", "zoominfo.com",
    "usphonebook.com", "nuwber.com", "searchpeoplefree.com",
}
# URL path fragments that mark a directory listing rather than a single profile
# (e.g. LinkedIn `/pub/dir`, Facebook `/directory/`), so we keep real `/in/<slug>` pages.
_DIRECTORY_PATHS = ("/pub/dir", "/directory/", "/dir/", "/profiles/", "/browse/")
# Titles that are clearly a directory of many same-named people: "50+ ... profiles".
_DIRECTORY_TITLE = re.compile(r"^\s*\d{1,4}\+?\s+.*\bprofiles?\b", re.I)


def is_directory_noise(url: str, title: str | None = None) -> bool:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host in _DIRECTORY_DOMAINS:
        return True
    path = (parsed.path or "").lower()
    if any(frag in path for frag in _DIRECTORY_PATHS):
        return True
    return bool(title and _DIRECTORY_TITLE.search(title))
