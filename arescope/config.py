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

    # Name → data-broker / people-search listings (root input: name). Provider-agnostic
    # and config-gated: point NAME_SEARCH_API_URL at your chosen people-search/broker API
    # (or a thin shim you host) and set the key. Absent => connector unavailable =>
    # honest coverage gap (never a failure), exactly like HIBP/Shodan. The connector
    # returns listing EXISTENCE + opt-out links only (the "normal" tier); the full
    # dossier (address/relatives/age) is the gated "extended" tier (name + verified
    # email — see docs/OWNERSHIP_VERIFICATION.md), built next.
    name_search_api_url: str = ""
    name_search_api_key: str = ""
    # Flipped on per-scan only when the name's ownership is verified via a linked email
    # (the extended dossier tier). Default off — name-only stays listing-existence.
    name_extended: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
