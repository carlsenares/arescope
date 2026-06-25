"""GitHub repo summarization + repo-node projection (pure, no network)."""

from __future__ import annotations

from types import SimpleNamespace

from arescope.connectors.github import _summarize_repos
from arescope.graph import _repo_nodes

_REPOS = [
    {"name": "aresis", "language": "Python", "stargazers_count": 50,
     "topics": ["osint", "privacy"], "html_url": "https://github.com/u/aresis",
     "description": "self-audit", "fork": False},
    {"name": "dotfiles", "language": "Shell", "stargazers_count": 3,
     "topics": [], "html_url": "https://github.com/u/dotfiles", "fork": False},
    {"name": "someone-else", "language": "Go", "stargazers_count": 999,
     "topics": ["k8s"], "html_url": "https://github.com/u/fork", "fork": True},  # fork excluded
]


def test_summarize_excludes_forks_and_ranks_by_stars():
    s = _summarize_repos(_REPOS)
    assert "Python" in s["languages"] and "Go" not in s["languages"]  # fork's lang excluded
    assert s["total_stars"] == 53                                     # 50 + 3, not the fork
    assert s["top_repos"][0]["name"] == "aresis"                      # most-starred first
    assert "osint" in s["topics"]
    assert all(r["name"] != "someone-else" for r in s["top_repos"])


def test_summarize_empty_is_safe():
    s = _summarize_repos([])
    assert s["languages"] == [] and s["top_repos"] == [] and s["total_stars"] == 0


def test_repo_nodes_content_addressed():
    sig = SimpleNamespace(kind="account", raw={"top_repos": [
        {"name": "aresis", "url": "https://github.com/u/aresis", "stars": 50,
         "language": "Python", "description": "self-audit"},
        {"name": "noname"},  # no url → keyed by name, still rendered
    ]})
    nodes = _repo_nodes(sig)
    assert len(nodes) == 2
    assert all(nid.startswith("repo:") for nid, _ in nodes)
    assert nodes[0][1]["label"] == "aresis"
    assert nodes[0][1]["meta"]["stars"] == 50


def test_repo_nodes_skip_malformed():
    sig = SimpleNamespace(kind="account", raw={"top_repos": [{"description": "no name"}, "junk"]})
    assert _repo_nodes(sig) == []
