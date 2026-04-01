"""Centralized configuration via pydantic-settings.

Loads from environment variables (KYRIAKI_ prefix) or .env file.
Also accepts ANTHROPIC_API_KEY without prefix for backwards compatibility.
"""

import os
from functools import lru_cache
from typing import List

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KYRIAKI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://kyriaki:kyriaki_dev@localhost:5432/kyriaki"

    # Claude API
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"

    # Matching engine
    match_timeout: int = 120
    max_concurrent_analyses: int = 1
    inter_call_delay: float = 2.0
    max_retries: int = 1
    default_page_size: int = 10

    # Trials client
    cache_ttl: int = 300

    # Server
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:3000"]
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "text"
    environment: str = "development"

    @model_validator(mode="after")
    def _load_anthropic_key_fallback(self):
        """Accept ANTHROPIC_API_KEY without the KYRIAKI_ prefix (backwards compat with .env)."""
        if not self.anthropic_api_key:
            self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
