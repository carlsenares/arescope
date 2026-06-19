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
        env_prefix="ARESIS_",
        extra="ignore",
    )

    # Core infra
    database_url: str = "postgresql+psycopg://aresis:aresis@localhost:5432/aresis"
    redis_url: str = "redis://localhost:6379/0"

    # PII encryption + retention (legal requirement from day one, ARCHITECTURE.md §4.4)
    encryption_key: str = ""
    retention_days: int = 30

    # LLM. anthropic SDK reads ANTHROPIC_API_KEY itself (no ARESIS_ prefix).
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
