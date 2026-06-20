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
    shodan_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
