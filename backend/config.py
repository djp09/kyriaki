"""Centralized configuration via pydantic-settings.

Loads from environment variables (KYRIAKI_ prefix) or .env file.
Also accepts ANTHROPIC_API_KEY without prefix for backwards compatibility.
Optionally fetches secrets from AWS Secrets Manager (set KYRIAKI_SECRETS_BACKEND=aws_secretsmanager).
"""

import logging
import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KYRIAKI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://kyriaki:kyriaki_dev@localhost:5432/kyriaki"

    # Secrets backend
    secrets_backend: str = "env"  # "env" (default) or "aws_secretsmanager"
    aws_secret_name: str = "kyriaki/api-keys"
    aws_region: str = "us-east-1"

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
    agent_max_analysis_calls: int = 10  # reduced for faster response times

    # Evaluator-optimizer loop
    evaluation_enabled: bool = True
    evaluation_score_min: int = 30  # Lower bound: below this is clearly poor, skip evaluation
    evaluation_score_max: int = 70  # Upper bound: above this is clearly strong, skip evaluation

    # Matching engine
    match_timeout: int = 180
    max_concurrent_analyses: int = 5
    inter_call_delay: float = 0.3
    max_retries: int = 3
    default_page_size: int = 10

    # Monitor agent
    monitor_enabled: bool = False
    monitor_interval_seconds: int = 3600

    # Pipeline auto-chaining
    auto_chain_matching_to_dossier: bool = False  # If True, auto-dispatch dossier after matching completes

    # Gemma (local LLM) — ADR-002 pipeline stages 1, 3, 4
    gemma_backend: str = "ollama"  # "ollama" | "vertex"
    ollama_host: str = "http://localhost:11434"
    gemma_generate_model: str = "gemma4"
    gemma_embed_model: str = "nomic-embed-text"
    # Gemma pipeline stage flags — enable individually for gradual rollout
    gemma_stage1_enabled: bool = True  # intake normalization (one call, ~12s local)
    gemma_stage3_enabled: bool = True  # semantic recall embeddings (one batch call)
    gemma_stage4_enabled: bool = False  # criterion extraction cache lookup (nightly sync only for now)
    # Vertex AI (unused until prod wiring)
    vertex_project: str = ""
    vertex_location: str = "us-central1"
    vertex_endpoint_id: str = ""

    # Trials client
    cache_ttl: int = 300  # In-memory cache TTL (seconds)
    trial_cache_ttl_hours: int = 24  # DB cache TTL for nightly refresh
    trial_refresh_enabled: bool = False  # Enable nightly background refresh
    trial_refresh_hour: int = 2  # Hour (UTC) to run nightly refresh

    # API key auth
    api_key: str = ""  # The key clients must provide; empty = no key configured
    api_key_enabled: bool = False  # Explicit toggle; False = auth disabled (dev mode)

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

    @model_validator(mode="after")
    def _load_secrets_from_aws(self):
        """If secrets_backend is 'aws_secretsmanager' and keys are missing, fetch from AWS."""
        if self.secrets_backend != "aws_secretsmanager":
            return self
        if self.anthropic_api_key:
            return self  # already populated, nothing to fetch

        try:
            import boto3  # noqa: F811
            from botocore.exceptions import ClientError
        except ImportError:
            logger.warning(
                "secrets_backend=aws_secretsmanager but boto3 is not installed; falling back to environment variables"
            )
            return self

        try:
            client = boto3.client("secretsmanager", region_name=self.aws_region)
            resp = client.get_secret_value(SecretId=self.aws_secret_name)
        except ClientError as exc:
            logger.warning(
                "Failed to fetch secret '%s' from AWS Secrets Manager: %s; falling back to environment variables",
                self.aws_secret_name,
                exc,
            )
            return self
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Unexpected error fetching from AWS Secrets Manager: %s; falling back to environment variables",
                exc,
            )
            return self

        import json

        try:
            secrets = json.loads(resp["SecretString"])
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning(
                "Could not parse secret '%s' as JSON: %s; falling back to environment variables",
                self.aws_secret_name,
                exc,
            )
            return self

        if not self.anthropic_api_key and "ANTHROPIC_API_KEY" in secrets:
            self.anthropic_api_key = secrets["ANTHROPIC_API_KEY"]

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
