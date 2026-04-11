"""Observability layer — per-call + per-run Claude metrics.

Every call routed through ``tools.claude_api`` records a ``CallMetric``
into a context-local ``RunMetrics`` collector. Entry points (the
matching engine and the agent dispatcher) bracket each run with
``start_run`` / ``end_run``, and completed runs land in an in-memory
ring buffer that ``/api/metrics/summary`` and ``/api/metrics/recent``
read from.

The collector is a contextvar so every task spawned inside a run (via
``asyncio.gather``, ``create_task``, etc.) inherits the active run
automatically — no manual threading of a metrics object.
"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from logging_config import get_logger

logger = get_logger("kyriaki.metrics")


# ---------------------------------------------------------------------------
# Pricing table (USD per 1M tokens, as of 2026-04)
# ---------------------------------------------------------------------------

# Prices sourced from https://www.anthropic.com/pricing. Cache-write is
# typically 1.25× base input; cache-read is 0.1× base input. Unknown models
# fall back to Sonnet pricing (the most common default).

PRICING: dict[str, dict[str, float]] = {
    # Opus 4 family
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_write": 18.75},
    "claude-opus-4-6[1m]": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_write": 18.75},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_write": 18.75},
    # Sonnet 4 family
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    "claude-sonnet-4-5-20250929": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    # Haiku 4 family
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_read": 0.10, "cache_write": 1.25},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0, "cache_read": 0.10, "cache_write": 1.25},
}

_FALLBACK_PRICE = PRICING["claude-sonnet-4-5-20250929"]


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """Return the approximate USD cost of a single Claude call."""
    price = PRICING.get(model, _FALLBACK_PRICE)
    return (
        input_tokens * price["input"]
        + output_tokens * price["output"]
        + cache_read_tokens * price["cache_read"]
        + cache_creation_tokens * price["cache_write"]
    ) / 1_000_000


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CallMetric:
    ts: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: float
    wall_ms: float
    agent: str = ""
    handler: str = ""
    run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "wall_ms": round(self.wall_ms, 1),
            "agent": self.agent,
            "handler": self.handler,
            "run_id": self.run_id,
        }


@dataclass
class RunMetrics:
    run_id: str
    agent: str
    started_at: str
    ended_at: str = ""
    calls: list[CallMetric] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def total_cache_read(self) -> int:
        return sum(c.cache_read_input_tokens for c in self.calls)

    @property
    def total_cache_creation(self) -> int:
        return sum(c.cache_creation_input_tokens for c in self.calls)

    @property
    def cache_hit_ratio(self) -> float:
        total = self.total_cache_read + self.total_cache_creation
        return self.total_cache_read / total if total else 0.0

    @property
    def total_cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    @property
    def wall_ms(self) -> float:
        if not (self.started_at and self.ended_at):
            return 0.0
        s = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
        e = datetime.fromisoformat(self.ended_at.replace("Z", "+00:00"))
        return (e - s).total_seconds() * 1000.0

    def to_summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "agent": self.agent,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "wall_ms": round(self.wall_ms, 1),
            "call_count": len(self.calls),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cache_read_tokens": self.total_cache_read,
            "total_cache_creation_tokens": self.total_cache_creation,
            "cache_hit_ratio": round(self.cache_hit_ratio, 3),
            "total_cost_usd": round(self.total_cost_usd, 4),
            "models_used": sorted({c.model for c in self.calls}),
        }

    def to_detail(self) -> dict[str, Any]:
        summary = self.to_summary()
        summary["calls"] = [c.to_dict() for c in self.calls]
        return summary


# ---------------------------------------------------------------------------
# Context-local collector
# ---------------------------------------------------------------------------

_current_run: ContextVar[RunMetrics | None] = ContextVar("_current_run", default=None)

# Ring buffer of completed runs (thread-safe via lock; bounded size).
_MAX_HISTORY = 512
_ring_buffer: deque[RunMetrics] = deque(maxlen=_MAX_HISTORY)
_lock = threading.Lock()


def start_run(agent: str, run_id: str | None = None) -> RunMetrics:
    """Begin a new metrics run in the current async context.

    Returns the fresh ``RunMetrics`` object. Subsequent Claude API calls
    made inside this context (including in child tasks from gather) will
    be recorded into it.
    """
    metrics = RunMetrics(
        run_id=run_id or str(uuid.uuid4()),
        agent=agent,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    _current_run.set(metrics)
    return metrics


def end_run() -> RunMetrics | None:
    """Finalise the current run and push it into the ring buffer."""
    metrics = _current_run.get()
    if metrics is None:
        return None
    metrics.ended_at = datetime.now(timezone.utc).isoformat()
    with _lock:
        _ring_buffer.append(metrics)
    _current_run.set(None)
    logger.info(
        "metrics.run_complete",
        run_id=metrics.run_id,
        agent=metrics.agent,
        wall_ms=metrics.wall_ms,
        call_count=len(metrics.calls),
        total_cost_usd=round(metrics.total_cost_usd, 4),
        cache_hit_ratio=round(metrics.cache_hit_ratio, 3),
    )
    return metrics


def current_run() -> RunMetrics | None:
    """Return the active run, or ``None`` outside a run context."""
    return _current_run.get()


def record_call(
    *,
    model: str,
    usage: Any,
    wall_ms: float,
    handler: str = "",
) -> CallMetric:
    """Record a completed Claude call into the current run (if any).

    ``usage`` is an Anthropic ``Usage`` object or any object with the
    fields ``input_tokens`` / ``output_tokens`` /
    ``cache_creation_input_tokens`` / ``cache_read_input_tokens``. Missing
    attributes are treated as zero so this is safe to call with partially
    populated usage objects.
    """
    input_t = int(getattr(usage, "input_tokens", 0) or 0)
    output_t = int(getattr(usage, "output_tokens", 0) or 0)
    cache_read_t = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cache_create_t = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    cost = estimate_cost(model, input_t, output_t, cache_read_t, cache_create_t)

    run = _current_run.get()
    call = CallMetric(
        ts=datetime.now(timezone.utc).isoformat(),
        model=model,
        input_tokens=input_t,
        output_tokens=output_t,
        cache_creation_input_tokens=cache_create_t,
        cache_read_input_tokens=cache_read_t,
        cost_usd=cost,
        wall_ms=wall_ms,
        agent=run.agent if run else "",
        handler=handler,
        run_id=run.run_id if run else "",
    )
    if run is not None:
        run.calls.append(call)
    return call


# ---------------------------------------------------------------------------
# Query helpers for the /api/metrics endpoints
# ---------------------------------------------------------------------------


def get_recent_runs(limit: int = 50) -> list[RunMetrics]:
    with _lock:
        if limit <= 0:
            return []
        return list(_ring_buffer)[-limit:]


def get_run(run_id: str) -> RunMetrics | None:
    with _lock:
        for run in reversed(_ring_buffer):
            if run.run_id == run_id:
                return run
    return None


def summary_rollup(window_seconds: int = 86400) -> dict[str, Any]:
    """Aggregate the last ``window_seconds`` of runs into one snapshot."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)

    with _lock:
        recent: list[RunMetrics] = []
        for r in _ring_buffer:
            if not r.started_at:
                continue
            try:
                started = datetime.fromisoformat(r.started_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if started >= cutoff:
                recent.append(r)

    if not recent:
        return {
            "window_seconds": window_seconds,
            "runs": 0,
            "total_calls": 0,
            "total_cost_usd": 0.0,
            "total_input_tokens": 0,
            "cache_hit_ratio": 0.0,
            "by_agent": {},
            "by_model": {},
        }

    total_cost = sum(r.total_cost_usd for r in recent)
    total_calls = sum(len(r.calls) for r in recent)
    total_input = sum(r.total_input_tokens for r in recent)
    total_output = sum(r.total_output_tokens for r in recent)
    total_cache_read = sum(r.total_cache_read for r in recent)
    total_cache_create = sum(r.total_cache_creation for r in recent)
    cache_total = total_cache_read + total_cache_create
    cache_hit_ratio = total_cache_read / cache_total if cache_total else 0.0

    by_agent: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    wall_samples: list[float] = []

    for run in recent:
        agent = run.agent or "unknown"
        agg = by_agent.setdefault(
            agent,
            {"runs": 0, "calls": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0},
        )
        agg["runs"] += 1
        agg["calls"] += len(run.calls)
        agg["cost_usd"] += run.total_cost_usd
        agg["input_tokens"] += run.total_input_tokens
        agg["output_tokens"] += run.total_output_tokens

        if run.wall_ms:
            wall_samples.append(run.wall_ms)

        for call in run.calls:
            model_agg = by_model.setdefault(
                call.model,
                {"calls": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0},
            )
            model_agg["calls"] += 1
            model_agg["cost_usd"] += call.cost_usd
            model_agg["input_tokens"] += call.input_tokens
            model_agg["output_tokens"] += call.output_tokens

    for agg in by_agent.values():
        agg["cost_usd"] = round(agg["cost_usd"], 4)
    for agg in by_model.values():
        agg["cost_usd"] = round(agg["cost_usd"], 4)

    wall_samples.sort()
    p50_wall = wall_samples[len(wall_samples) // 2] if wall_samples else 0.0
    p95_index = max(0, int(len(wall_samples) * 0.95) - 1)
    p95_wall = wall_samples[p95_index] if wall_samples else 0.0

    return {
        "window_seconds": window_seconds,
        "runs": len(recent),
        "total_calls": total_calls,
        "total_cost_usd": round(total_cost, 4),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cache_read_tokens": total_cache_read,
        "total_cache_creation_tokens": total_cache_create,
        "cache_hit_ratio": round(cache_hit_ratio, 3),
        "avg_cost_per_run": round(total_cost / len(recent), 4),
        "p50_wall_ms": round(p50_wall, 1),
        "p95_wall_ms": round(p95_wall, 1),
        "by_agent": by_agent,
        "by_model": by_model,
    }


def clear_history() -> None:
    """Test helper — wipe the ring buffer."""
    with _lock:
        _ring_buffer.clear()
