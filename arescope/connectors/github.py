"""GitHub — a username's public profile (#4 footprint, #5 identity metadata).

Consumes: username. Free public REST API (api.github.com). An optional token
(ARESCOPE_GITHUB_TOKEN) lifts the rate limit 60→5000/hr; unauthenticated still
works. Surfaces the real-world identity a dev handle leaks: name, location,
company, email, avatar, and the linked Twitter/blog (deanonymization vectors).
"""

from __future__ import annotations

from collections import Counter

import httpx

from arescope.config import Settings
from arescope.connectors._identity import LINK, PHOTO, from_profile_fields, identity_signal
from arescope.connectors.base import Connector, ConnectorGap
from arescope.schemas import InputType, Signal

_API = "https://api.github.com/users/"
_TOP_REPOS = 6   # how many of the user's own repos to surface on the map / for inference


def _summarize_repos(repos: list[dict]) -> dict:
    """Aggregate a user's OWN public repos into inference-ready facts (no forks).

    Languages + topics hint at what they work on; the top repos (by stars) are the
    public projects worth a node. Pure + defensive — feeds the map now and Opus
    Evaluate later (the "what do their repos reveal" inference).
    """
    own = [r for r in repos if isinstance(r, dict) and not r.get("fork")]
    langs = Counter(r["language"] for r in own if r.get("language"))
    topics: Counter = Counter()
    for r in own:
        for t in (r.get("topics") or []):
            topics[t] += 1
    top = sorted(own, key=lambda r: r.get("stargazers_count") or 0, reverse=True)[:_TOP_REPOS]
    return {
        "languages": [lang for lang, _ in langs.most_common(8)],
        "topics": [t for t, _ in topics.most_common(10)],
        "total_stars": sum(r.get("stargazers_count") or 0 for r in own),
        "top_repos": [
            {"name": r.get("name"), "url": r.get("html_url"),
             "description": (r.get("description") or "")[:140],
             "stars": r.get("stargazers_count") or 0, "language": r.get("language")}
            for r in top if r.get("name")
        ],
    }


class GitHubConnector(Connector):
    name = "github"
    consumes = {InputType.USERNAME}

    def available(self, cfg: Settings) -> bool:
        return cfg.github_enabled

    def _repo_summary(self, username: str, headers: dict) -> dict:
        """Fetch the user's public repos and summarize. Best-effort: any failure returns
        {} so the profile signal still lands (repos are a bonus, not a gap)."""
        try:
            resp = httpx.get(f"{_API}{username}/repos", headers=headers, timeout=20,
                             params={"sort": "pushed", "direction": "desc",
                                     "per_page": 100, "type": "owner"})
        except httpx.HTTPError:
            return {}
        if resp.status_code != 200:
            return {}
        repos = resp.json()
        return _summarize_repos(repos) if isinstance(repos, list) else {}

    def run(self, value: str, input_type: InputType, cfg: Settings) -> list[Signal]:
        headers = {"accept": "application/vnd.github+json", "user-agent": "arescope-self-audit"}
        if cfg.github_token:
            headers["authorization"] = f"Bearer {cfg.github_token}"
        try:
            resp = httpx.get(f"{_API}{value}", headers=headers, timeout=20, follow_redirects=True)
        except httpx.HTTPError as e:
            raise ConnectorGap(f"github request failed: {e}") from e

        if resp.status_code == 404:
            return []  # no such user — not a gap, just absence
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            raise ConnectorGap("github rate-limited (set ARESCOPE_GITHUB_TOKEN to raise the limit)")
        if resp.status_code >= 400:
            raise ConnectorGap(f"github returned {resp.status_code}")

        data = resp.json() or {}
        profile_url = data.get("html_url")

        # Public repos → languages / topics / top projects (inference fuel + map nodes).
        repo_summary = self._repo_summary(value, headers)

        signals: list[Signal] = [
            Signal(
                source=self.name,
                kind="account",
                locator="github.com",
                subject_value=value,
                subject_type=InputType.USERNAME,
                raw={
                    "domain": "github.com",
                    "url": profile_url,
                    "public_repos": data.get("public_repos"),
                    "followers": data.get("followers"),
                    "created_at": data.get("created_at"),
                    **repo_summary,
                },
            )
        ]

        # Identity attributes the profile leaks (name/location/company/bio).
        fields: dict[str, object] = {
            "name": data.get("name"),
            "location": data.get("location"),
            "company": data.get("company"),
            "bio": data.get("bio"),
        }
        signals.extend(
            from_profile_fields(
                source=self.name,
                platform="github.com",
                fields=fields,
                subject_value=value,
                subject_type=InputType.USERNAME,
                profile_url=profile_url,
            )
        )
        # The avatar as a real face on the map. GitHub's API exposes no "is this the
        # default identicon" flag, so we surface it as a photo (real uploads dominate
        # among real accounts) and let the proxy/monogram fallback handle a miss.
        if data.get("avatar_url"):
            signals.append(identity_signal(
                source=self.name, attribute=PHOTO, value=str(data["avatar_url"]),
                subject_value=value, subject_type=InputType.USERNAME, platform="github.com"))

        # A public email or a linked handle is a direct pivot to other identities.
        if data.get("email"):
            signals.append(
                identity_signal(
                    source=self.name, attribute=LINK, value=str(data["email"]),
                    subject_value=value, subject_type=InputType.USERNAME,
                    platform="github.com", url=f"mailto:{data['email']}",
                )
            )
        if data.get("twitter_username"):
            signals.append(
                identity_signal(
                    source=self.name, attribute=LINK, value=f"@{data['twitter_username']} (x.com)",
                    subject_value=value, subject_type=InputType.USERNAME,
                    platform="github.com", url=f"https://x.com/{data['twitter_username']}",
                )
            )
        if data.get("blog"):
            url = str(data["blog"])
            signals.append(
                identity_signal(
                    source=self.name, attribute=LINK, value=url,
                    subject_value=value, subject_type=InputType.USERNAME,
                    platform="github.com", url=url if url.startswith("http") else f"https://{url}",
                )
            )
        return signals
