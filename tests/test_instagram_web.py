"""Instagram-web parser + post-node projection (no browser / network needed)."""

from __future__ import annotations

from types import SimpleNamespace

from arescope.config import Settings
from arescope.connectors.instagram_web import InstagramWebConnector, _parse_web_profile_info
from arescope.graph import _post_nodes

_SAMPLE = {
    "data": {"user": {
        "full_name": "Jane Doe",
        "biography": "coffee + code in Cologne",
        "is_private": False,
        "is_verified": True,
        "profile_pic_url_hd": "https://example.com/jane.jpg",
        "edge_followed_by": {"count": 1234},
        "edge_owner_to_timeline_media": {"edges": [
            {"node": {
                "edge_media_to_caption": {"edges": [{"node": {"text": "morning espresso"}}]},
                "location": {"name": "Cologne, Germany"},
            }},
            {"node": {
                "edge_media_to_caption": {"edges": [{"node": {"text": "weekend hike"}}]},
                "location": None,
            }},
        ]},
    }}
}


def test_parse_extracts_account_photo_and_location():
    sigs = _parse_web_profile_info(_SAMPLE, "janedoe")
    account = [s for s in sigs if s.kind == "account"]
    assert len(account) == 1
    raw = account[0].raw
    assert raw["display_name"] == "Jane Doe"
    assert raw["followers"] == 1234
    assert raw["recent_posts"] == ["morning espresso", "weekend hike"]

    attrs = [s for s in sigs if s.kind == "identity_attribute"]
    photos = [s for s in attrs if s.raw["attribute"] == "photo"]
    locations = [s for s in attrs if s.raw["attribute"] == "location"]
    assert photos and photos[0].raw["value"] == "https://example.com/jane.jpg"
    assert locations and locations[0].raw["value"] == "Cologne, Germany"


def test_private_profile_omits_photo():
    data = {"data": {"user": {**_SAMPLE["data"]["user"], "is_private": True}}}
    sigs = _parse_web_profile_info(data, "janedoe")
    assert not [s for s in sigs if s.kind == "identity_attribute" and s.raw["attribute"] == "photo"]


def test_empty_user_is_clean():
    assert _parse_web_profile_info({"data": {"user": {}}}, "ghost") == []


def test_connector_unavailable_without_camoufox():
    # browser extra isn't installed in CI → connector cleanly reports unavailable.
    cfg = Settings(browser_scraping_enabled=True)
    assert InstagramWebConnector().available(cfg) is False
    assert InstagramWebConnector().admin_only is True


def test_post_nodes_are_content_addressed():
    sig = SimpleNamespace(kind="account", raw={
        "domain": "instagram.com", "recent_posts": ["morning espresso", "weekend hike", ""],
    })
    nodes = _post_nodes(sig)
    assert len(nodes) == 2  # blank dropped
    ids = [nid for nid, _ in nodes]
    assert all(nid.startswith("post:") for nid in ids)
    # same caption+platform => same id (dedup/convergence)
    again = _post_nodes(SimpleNamespace(kind="account", raw={
        "domain": "instagram.com", "recent_posts": ["morning espresso"]}))
    assert again[0][0] == ids[0]
