"""API key authentication dependency for FastAPI.

Simple Bearer token auth that validates against a configured key.
When api_key_enabled is False (default), auth is a no-op for dev mode.
Designed as a foundation for later JWT/Auth0 upgrade.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import Settings, get_settings

# Optional bearer scheme — auto_error=False so we handle missing tokens ourselves
_bearer_scheme = HTTPBearer(auto_error=False)


async def require_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """FastAPI dependency that enforces API key auth.

    Skips auth when:
    - api_key_enabled is False (dev mode)
    - The request is an OPTIONS preflight
    - The path is /api/health
    """
    if not settings.api_key_enabled:
        return

    if request.method == "OPTIONS":
        return

    if request.url.path == "/api/health":
        return

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={"error": True, "message": "Missing API key. Provide Authorization: Bearer <key> header."},
        )

    if credentials.credentials != settings.api_key:
        raise HTTPException(
            status_code=401,
            detail={"error": True, "message": "Invalid API key."},
        )
