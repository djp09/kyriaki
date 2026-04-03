"""Centralized configuration via pydantic-settings.

Loads from environment variables (KYRIAKI_ prefix) or .env file.
Also accepts ANTHROPIC_API_KEY without prefix for backwards compatibility.
"""

import os
from functools import lru_cache

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

    # Dossier agent
    dossier_model: str = "claude-opus-4-20250514"
    dossier_max_tokens: int = 4096
    dossier_top_n: int = 3
    dossier_max_concurrent: int = 3

    # Agent loop (adaptive matching)
    agent_max_iterations: int = 5
    agent_max_search_calls: int = 3
    agent_max_analysis_calls: int = 20

    # Evaluator-optimizer loop
    evaluation_enabled: bool = True
    evaluation_score_min: int = 30  # Lower bound: below this is clearly poor, skip evaluation
    evaluation_score_max: int = 70  # Upper bound: above this is clearly strong, skip evaluation

    # Matching engine
    match_timeout: int = 180
    max_concurrent_analyses: int = 10
    inter_call_delay: float = 0.0
    max_retries: int = 3
    default_page_size: int = 10

    # Monitor agent
    monitor_enabled: bool = False
    monitor_interval_seconds: int = 3600

    # Pipeline auto-chaining
    auto_chain_matching_to_dossier: bool = False  # If True, auto-dispatch dossier after matching completes

    # Trials client
    cache_ttl: int = 300

    # Server
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
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
