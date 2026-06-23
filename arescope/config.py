"""Central configuration. Secrets via env / .env (gitignored).

Connectors are config-gated here (ARCHITECTURE.md §4.3): each reads its enable
flag / key from this object, so Phase 0 runs on free tiers and paid sources are
added without code changes.
"""

from __future__ import annotations

from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Surface .env into the process environment so unprefixed, third-party-convention
# vars (notably ANTHROPIC_API_KEY, which the anthropic SDK reads from os.environ)
# are visible on local runs too. override=False => real env (Docker) still wins.
load_dotenv(override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ARESCOPE_",
        extra="ignore",
    )

    # Core infra
    database_url: str = "postgresql+psycopg://arescope:arescope@localhost:5432/arescope"
    redis_url: str = "redis://localhost:6379/0"

    # PII encryption + retention (legal requirement from day one, ARCHITECTURE.md §4.4)
    encryption_key: str = ""
    retention_days: int = 30
    # Where uploaded photos are saved (EXIF). Shared volume so the worker (separate
    # container) can read what the api wrote. Local dev falls back to a temp dir.
    upload_dir: str = "/data/uploads"

    # Web app + auth (self-hosted; no third-party identity provider — the product's
    # data-minimization promise extends to its own accounts).
    session_secret: str = "dev-insecure-change-me"  # signs the session cookie
    session_max_age: int = 60 * 60 * 24 * 14  # 14 days; keeps users logged in
    cookie_secure: bool = False  # set True behind HTTPS in production
    base_url: str = "http://localhost:8000"

    # Outbound email (magic-link login + signup email verification). Provider-agnostic:
    # if resend_api_key is set we send via Resend; otherwise the mailer falls back to
    # logging the link to the console (so local dev needs no key and never fails a flow).
    resend_api_key: str = ""
    email_from: str = "Arescope <noreply@arescope.com>"
    magic_link_ttl_minutes: int = 30  # how long a login/verify link stays valid

    # Admin seed — consumed by `python -m arescope.cli create-admin`.
    admin_email: str = ""
    admin_username: str = ""
    admin_password: str = ""

    # LLM. anthropic SDK reads ANTHROPIC_API_KEY itself (no ARESCOPE_ prefix).
    # Tiered (AI_PIPELINE.md): Haiku triages 100% of clusters, Opus judges the
    # escalated head + writes involved remediations.
    triage_model: str = "claude-haiku-4-5"
    judge_model: str = "claude-opus-4-8"
    remediation_model: str = "claude-opus-4-8"

    # Connectors
    hibp_api_key: str = ""
    hudsonrock_enabled: bool = True
    holehe_enabled: bool = True
    maigret_enabled: bool = True
    # Cap Maigret to the N most popular sites (None => its default ~500). A scan can
    # override this per-run (the "top sites only, faster" choice on the form).
    maigret_top_sites: int | None = None
    shodan_api_key: str = ""

    # Extended search — free identity-enrichment connectors (EXTENDED_SEARCH_SCOPE.md).
    # All on by default: they read only the public profile of an identifier the user
    # submitted as their own, so they're self-audit-safe on every tier.
    github_enabled: bool = True
    github_token: str = ""  # optional: lifts the API rate limit 60→5000/hr
    reddit_enabled: bool = True
    # Reddit now 403-blocks unauthenticated .json from datacenter IPs. A free Reddit
    # "script" app (client id+secret) enables the OAuth app-only API; absent => the
    # connector tries the public endpoint and reports a coverage gap if blocked.
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    gravatar_enabled: bool = True

    # Extended search — key/credential-gated drop-ins. Absent => connector unavailable
    # => honest coverage gap (never a failure). Acquire + drop the value in to light up.
    # GHunt needs a Google session cookie file; the rest are paid API keys. The admin-
    # only sources (brave/apify/intelx/facecheck) also need the per-connector admin gate
    # before they run for non-admins — see EXTENDED_SEARCH_SCOPE.md build order.
    ghunt_creds_path: str = ""
    brave_api_key: str = ""
    apify_token: str = ""
    dehashed_api_key: str = ""
    intelx_api_key: str = ""
    facecheck_api_key: str = ""

    # Name → data-broker / people-search listings (root input: name). Provider-agnostic
    # and config-gated: point NAME_SEARCH_API_URL at your chosen people-search/broker API
    # (or a thin shim you host) and set the key. Absent => connector unavailable =>
    # honest coverage gap (never a failure), exactly like HIBP/Shodan. The connector
    # returns listing EXISTENCE + opt-out links only (the "normal" tier); the full
    # dossier (address/relatives/age) is the gated "extended" tier (name + verified
    # email — see docs/OWNERSHIP_VERIFICATION.md), built next.
    name_search_api_url: str = ""
    name_search_api_key: str = ""
    # Free, no-key fallback for the name connector: enumerate the consumer people-search
    # brokers + opt-out links (the removal track) when no paid lookup is configured. On by
    # default — it's a bundled catalog, not a paid source. Results are listing-existence-
    # AGNOSTIC (we don't confirm the name is listed); the connector marks them confirmed:false.
    broker_registry_enabled: bool = True
    # How many brokers the free enumeration catalog returns, most-prominent first. The
    # catalog has ~30; dumping all of them produced an unrealistic "go check these 30
    # sites and report back" finding. Cap it to the brokers a person is most likely on so
    # the removal checklist stays actionable. 0/None => no cap (return the whole catalog).
    broker_top_n: int = 12
    # Flipped on per-scan only when the name's ownership is verified via a linked email
    # (the extended dossier tier). Default off — name-only stays listing-existence.
    name_extended: bool = False

    # --- Expansion batch (2026-06-23): individually-obtainable sources ---------
    # All key-gated and graceful (absent => coverage gap, never a failure).
    # See docs/CONNECTOR_EXPANSION_PLAN.md.
    leakcheck_api_key: str = ""    # email/username/phone breach exposure (credential depth)
    ipinfo_token: str = ""         # IP geo / ASN / hosting-vs-residential
    abuseipdb_api_key: str = ""    # IP abuse/blocklist reputation
    censys_token: str = ""         # IP host/service exposure (Censys Platform PAT)
    # VirusTotal is NON-COMMERCIAL-USE-ONLY per its free-tier licence -> admin-only,
    # must never run in a commercial product build.
    virustotal_api_key: str = ""   # IP/domain reputation (admin-only)
    urlscan_api_key: str = ""      # where an identifier appears in scanned pages
    ipqs_api_key: str = ""         # phone fraud/spam reputation + line type
    numverify_api_key: str = ""    # phone validation: carrier / geo / line type
    wayback_enabled: bool = True   # historical web mentions (open API, no key)

    # Self-hosted tools (no key; gated on the lib/CLI being installed -> else simply
    # unavailable, no coverage-gap noise). Install via the [connectors] extra / image.
    exif_enabled: bool = True      # photo: read embedded GPS/camera from an image file
    sherlock_enabled: bool = True  # username: account presence cross-check (Maigret backup)
    ignorant_enabled: bool = True  # phone: which sites a number is registered on


@lru_cache
def get_settings() -> Settings:
    return Settings()
