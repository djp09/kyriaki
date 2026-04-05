"""Gemma LLM client — self-hosted inference for PHI-sensitive pipeline stages.

Per ADR-002, stages 1 (intake normalization), 3 (embeddings), and 4 (criterion
extraction) run on local Gemma so raw PHI never leaves the box. Claude only
sees de-identified, structured output.

Backends:
    - ollama: local dev (http://localhost:11434)
    - vertex: Vertex AI Gemma endpoint (service-account auth) — stub, not yet wired

Usage:
    client = get_gemma_client()
    result = await client.generate(prompt, schema=MySchema)
    vectors = await client.embed(["patient summary ..."])
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class GemmaError(Exception):
    """Raised when Gemma call fails irrecoverably."""


class GemmaSchemaError(GemmaError):
    """Raised when model output can't be parsed against the target schema after retries."""


class GemmaClient:
    """Abstract interface. Concrete backends: OllamaGemmaClient, VertexGemmaClient."""

    async def generate(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        max_retries: int = 2,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> str | BaseModel:
        raise NotImplementedError

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class OllamaGemmaClient(GemmaClient):
    """Ollama-backed Gemma client for local development."""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        generate_model: str = "gemma3:12b",
        embed_model: str = "nomic-embed-text",
        timeout: float = 120.0,
    ):
        self.host = host.rstrip("/")
        self.generate_model = generate_model
        self.embed_model = embed_model
        self.timeout = timeout

    async def generate(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        max_retries: int = 2,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> str | BaseModel:
        """Call Gemma. If schema is provided, parse + validate + retry on failure."""
        if schema is None:
            return await self._call_generate(prompt, temperature, max_tokens, json_mode=False)

        # Structured output: inject JSON schema into prompt, use JSON mode, validate.
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        structured_prompt = (
            f"{prompt}\n\n"
            f"You MUST respond with ONLY a JSON object matching this schema. "
            f"No markdown fences, no commentary, just the JSON.\n\n"
            f"JSON schema:\n{schema_json}\n"
        )

        last_error: str | None = None
        current_prompt = structured_prompt
        for attempt in range(max_retries + 1):
            raw = await self._call_generate(current_prompt, temperature, max_tokens, json_mode=True)
            try:
                data = json.loads(raw)
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = str(e)
                logger.warning(
                    "gemma schema validation failed",
                    extra={"attempt": attempt, "error": last_error, "raw_preview": raw[:300]},
                )
                if attempt < max_retries:
                    # Feed the error back to Gemma for a corrective retry.
                    current_prompt = (
                        f"{structured_prompt}\n\n"
                        f"Your previous response failed validation with error:\n{last_error}\n"
                        f"Previous response was:\n{raw[:500]}\n\n"
                        f"Respond again with ONLY valid JSON matching the schema."
                    )

        raise GemmaSchemaError(
            f"Failed to parse Gemma output against {schema.__name__} after {max_retries + 1} attempts. "
            f"Last error: {last_error}"
        )

    async def _call_generate(self, prompt: str, temperature: float, max_tokens: int, *, json_mode: bool) -> str:
        payload: dict[str, Any] = {
            "model": self.generate_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            resp = await http.post(f"{self.host}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data.get("response", "")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of strings. Ollama's /api/embed supports batch input."""
        if not texts:
            return []
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            resp = await http.post(
                f"{self.host}/api/embed",
                json={"model": self.embed_model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
        return data.get("embeddings", [])


class VertexGemmaClient(GemmaClient):
    """Vertex AI Gemma endpoint — stub. Implement when deploying to prod."""

    def __init__(self, project: str, location: str, endpoint_id: str):
        self.project = project
        self.location = location
        self.endpoint_id = endpoint_id

    async def generate(self, prompt: str, **kwargs: Any) -> str | BaseModel:
        raise NotImplementedError("Vertex backend not yet implemented — use ollama for dev")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Vertex backend not yet implemented — use ollama for dev")


_client: GemmaClient | None = None


def get_gemma_client() -> GemmaClient:
    """Return a configured Gemma client based on settings.gemma_backend."""
    global _client
    if _client is not None:
        return _client

    from config import get_settings

    settings = get_settings()
    backend = settings.gemma_backend.lower()

    if backend == "ollama":
        _client = OllamaGemmaClient(
            host=settings.ollama_host,
            generate_model=settings.gemma_generate_model,
            embed_model=settings.gemma_embed_model,
        )
    elif backend == "vertex":
        _client = VertexGemmaClient(
            project=settings.vertex_project,
            location=settings.vertex_location,
            endpoint_id=settings.vertex_endpoint_id,
        )
    else:
        raise GemmaError(f"Unknown GEMMA_BACKEND: {backend!r} (expected 'ollama' or 'vertex')")

    return _client


def reset_gemma_client() -> None:
    """Reset the cached singleton — useful in tests."""
    global _client
    _client = None
