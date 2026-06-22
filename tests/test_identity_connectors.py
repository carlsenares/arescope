"""Extended-search identity connectors + the identity_attribute wiring (no network)."""

from types import SimpleNamespace

from arescope.config import Settings
from arescope.connectors._identity import IDENTITY_KIND, from_profile_fields
from arescope.connectors.github import GitHubConnector
from arescope.connectors.gravatar import GravatarConnector
from arescope.connectors.reddit import RedditConnector
from arescope.graph import _classify as graph_classify
from arescope.pipeline.clustering import cluster_evidence
from arescope.pipeline.normalizer import normalize
from arescope.schemas import Category, InputType


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = ""

    def json(self):
        return self._payload


# --- _identity helper --------------------------------------------------------

def test_from_profile_fields_maps_and_dedups():
    sigs = list(
        from_profile_fields(
            source="maigret", platform="github.com",
            fields={"fullname": "Jane Doe", "city": "Berlin", "avatar": "http://x/a.png",
                    "unknown_field": "ignored", "name": "Jane Doe"},  # dup name dropped
            subject_value="jdoe", subject_type=InputType.USERNAME,
            profile_url="https://github.com/jdoe",
        )
    )
    attrs = sorted((s.raw["attribute"], s.raw["value"]) for s in sigs)
    assert attrs == [("location", "Berlin"), ("name", "Jane Doe"), ("photo", "http://x/a.png")]
    assert all(s.kind == IDENTITY_KIND for s in sigs)
    photo = next(s for s in sigs if s.raw["attribute"] == "photo")
    assert photo.raw["url"] == "http://x/a.png"  # photo url is the value itself


# --- GitHub ------------------------------------------------------------------

def test_github_emits_account_and_identity(monkeypatch):
    profile = {
        "html_url": "https://github.com/jdoe", "name": "Jane Doe", "location": "Berlin",
        "company": "Acme", "bio": "hi", "email": "jane@acme.com", "twitter_username": "janed",
        "blog": "https://jane.dev", "public_repos": 12, "followers": 30,
        "gravatar_id": "abc", "avatar_url": "https://avatars/u?v=4",
    }
    monkeypatch.setattr("arescope.connectors.github.httpx.get", lambda *a, **k: _Resp(profile))
    sigs = GitHubConnector().run("jdoe", InputType.USERNAME, Settings())
    kinds = [s.kind for s in sigs]
    assert "account" in kinds
    attrs = {s.raw.get("attribute") for s in sigs if s.kind == IDENTITY_KIND}
    assert {"name", "location", "company", "photo", "link"} <= attrs
    # the linked email + twitter become deanon "link" attributes
    link_vals = {s.raw["value"] for s in sigs if s.raw.get("attribute") == "link"}
    assert any("jane@acme.com" in v for v in link_vals)


def test_github_404_is_absence_not_gap(monkeypatch):
    monkeypatch.setattr("arescope.connectors.github.httpx.get",
                        lambda *a, **k: _Resp({}, status=404))
    assert GitHubConnector().run("ghost", InputType.USERNAME, Settings()) == []


# --- Reddit ------------------------------------------------------------------

def test_reddit_emits_account_and_subreddit_location(monkeypatch):
    about = _Resp({"data": {"total_karma": 500, "icon_img": "https://i/avatar_default_3.png"}})
    comments = _Resp({"data": {"children": [
        {"data": {"subreddit": "berlin"}}, {"data": {"subreddit": "berlin"}},
        {"data": {"subreddit": "python"}},
    ]}})

    def fake_get(url, *a, **k):
        return comments if "comments" in url else about

    monkeypatch.setattr("arescope.connectors.reddit.httpx.get", fake_get)
    sigs = RedditConnector().run("jdoe", InputType.USERNAME, Settings())
    assert any(s.kind == "account" and s.locator == "reddit.com" for s in sigs)
    loc = [s for s in sigs if s.raw.get("attribute") == "location"]
    assert loc and "berlin" in loc[0].raw["value"]


def test_reddit_403_is_coverage_gap_not_absence(monkeypatch):
    # A datacenter-IP login wall must surface as a gap, never imply "no Reddit account".
    import pytest

    from arescope.connectors.base import ConnectorGap
    monkeypatch.setattr("arescope.connectors.reddit.httpx.get",
                        lambda *a, **k: _Resp({}, status=403))
    with pytest.raises(ConnectorGap):
        RedditConnector().run("jdoe", InputType.USERNAME, Settings())


# --- Gravatar ----------------------------------------------------------------

def test_gravatar_emits_identity_and_linked_accounts(monkeypatch):
    payload = {"entry": [{
        "profileUrl": "https://gravatar.com/jdoe", "displayName": "Jane",
        "currentLocation": "Berlin", "thumbnailUrl": "https://gr/a.png",
        "name": {"formatted": "Jane Doe"},
        "accounts": [{"domain": "github.com", "url": "https://github.com/jdoe", "username": "jdoe"}],
    }]}
    monkeypatch.setattr("arescope.connectors.gravatar.httpx.get", lambda *a, **k: _Resp(payload))
    sigs = GravatarConnector().run("jane@acme.com", InputType.EMAIL, Settings())
    assert any(s.kind == "account" and s.locator == "github.com" for s in sigs)  # discovered handle
    attrs = {s.raw.get("attribute") for s in sigs if s.kind == IDENTITY_KIND}
    assert {"name", "location", "photo"} <= attrs


# --- wiring: clustering + graph ---------------------------------------------

def _isig(attribute, value, platform="github.com"):
    from arescope.connectors._identity import identity_signal
    return identity_signal(source="github", attribute=attribute, value=value,
                           subject_value="jdoe", subject_type=InputType.USERNAME,
                           platform=platform, url=value if attribute == "photo" else None)


def test_identity_attributes_cluster_to_metadata_and_photo():
    sigs = [_isig("name", "Jane Doe"), _isig("location", "Berlin"),
            _isig("photo", "https://x/a.png")]
    clusters = {c.category_hint for c in cluster_evidence(normalize(sigs))}
    assert Category.ACCOUNT_METADATA in clusters  # name + location
    assert Category.FACE_PHOTO_EXPOSURE in clusters  # photo split out


def test_identity_photo_and_location_graph_nodes():
    sig = SimpleNamespace(source="github", kind="identity_attribute", locator="github.com:photo",
                          raw={"attribute": "photo", "value": "https://x/a.png",
                               "platform": "github.com", "url": "https://x/a.png"})
    node = graph_classify(sig)
    assert node and node[1]["type"] == "photo" and node[1]["url"] == "https://x/a.png"

    loc = SimpleNamespace(source="github", kind="identity_attribute", locator="github.com:location",
                          raw={"attribute": "location", "value": "Berlin", "platform": "github.com"})
    lnode = graph_classify(loc)
    assert lnode and lnode[0] == "location:berlin" and lnode[1]["type"] == "location"


def test_github_account_becomes_site_node():
    sig = SimpleNamespace(source="github", kind="account", locator="github.com",
                          raw={"domain": "github.com", "url": "https://github.com/jdoe"})
    node = graph_classify(sig)
    assert node and node[0] == "site:github.com" and node[1]["type"] == "site"
