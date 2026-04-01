"""FastAPI middleware for request logging and tracing."""

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from logging_config import get_logger, request_id_var

logger = get_logger("kyriaki.http")

# Paths to skip logging (too noisy)
_SKIP_PATHS = frozenset({"/api/health"})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:16])
        request_id_var.set(request_id)

        if request.url.path in _SKIP_PATHS:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

        start = time.monotonic()
        logger.info(
            "request.start",
            method=request.method,
            path=request.url.path,
            client=request.client.host if request.client else None,
        )

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            logger.exception("request.error", method=request.method, path=request.url.path, duration_ms=duration_ms)
            raise

        duration_ms = round((time.monotonic() - start) * 1000, 1)
        logger.info(
            "request.complete",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response
