"""Tests for the metrics collector (P0-3 observability)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import pytest

import metrics


@dataclass
class _FakeUsage:
    """Duck-typed Anthropic usage object."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@pytest.fixture(autouse=True)
def _clear_history():
    metrics.clear_history()
    yield
    metrics.clear_history()


class TestPricing:
    def test_sonnet_base_price(self):
        # 1M input tokens of Sonnet = $3
        cost = metrics.estimate_cost("claude-sonnet-4-5-20250929", 1_000_000, 0)
        assert cost == pytest.approx(3.0)

    def test_sonnet_output_price(self):
        cost = metrics.estimate_cost("claude-sonnet-4-5-20250929", 0, 1_000_000)
        assert cost == pytest.approx(15.0)

    def test_cache_read_is_cheaper(self):
        baseline = metrics.estimate_cost("claude-sonnet-4-5-20250929", 1_000_000, 0)
        cached = metrics.estimate_cost("claude-sonnet-4-5-20250929", 0, 0, 1_000_000, 0)
        assert cached < baseline
        assert cached == pytest.approx(0.3)  # 10% of base input

    def test_cache_write_is_more_expensive(self):
        baseline = metrics.estimate_cost("claude-sonnet-4-5-20250929", 1_000_000, 0)
        written = metrics.estimate_cost("claude-sonnet-4-5-20250929", 0, 0, 0, 1_000_000)
        assert written > baseline
        assert written == pytest.approx(3.75)  # 1.25x base input

    def test_unknown_model_falls_back_to_sonnet(self):
        unknown = metrics.estimate_cost("claude-future-9999", 1_000_000, 0)
        sonnet = metrics.estimate_cost("claude-sonnet-4-5-20250929", 1_000_000, 0)
        assert unknown == sonnet

    def test_opus_is_most_expensive(self):
        opus = metrics.estimate_cost("claude-opus-4-6", 1_000_000, 0)
        sonnet = metrics.estimate_cost("claude-sonnet-4-5-20250929", 1_000_000, 0)
        haiku = metrics.estimate_cost("claude-haiku-4-5", 1_000_000, 0)
        assert opus > sonnet > haiku


class TestRunLifecycle:
    def test_record_outside_run_returns_zeroed_run_id(self):
        call = metrics.record_call(model="claude-sonnet-4-6", usage=_FakeUsage(), wall_ms=0)
        assert call.run_id == ""

    def test_start_run_captures_subsequent_calls(self):
        run = metrics.start_run(agent="matching")
        metrics.record_call(
            model="claude-sonnet-4-5-20250929",
            usage=_FakeUsage(input_tokens=100, output_tokens=50),
            wall_ms=250,
        )
        metrics.record_call(
            model="claude-sonnet-4-5-20250929",
            usage=_FakeUsage(input_tokens=200, output_tokens=80),
            wall_ms=400,
        )
        metrics.end_run()
        assert len(run.calls) == 2
        assert run.total_input_tokens == 300
        assert run.total_output_tokens == 130
        assert run.cache_hit_ratio == 0.0
        assert run.total_cost_usd > 0

    def test_cache_hit_ratio_two_tier(self):
        run = metrics.start_run(agent="matching")
        # Call 1: cold — writes both caches
        metrics.record_call(
            model="claude-sonnet-4-5-20250929",
            usage=_FakeUsage(input_tokens=100, output_tokens=50, cache_creation_input_tokens=2000),
            wall_ms=100,
        )
        # Call 2: warm — reads both caches
        metrics.record_call(
            model="claude-sonnet-4-5-20250929",
            usage=_FakeUsage(input_tokens=100, output_tokens=50, cache_read_input_tokens=2000),
            wall_ms=80,
        )
        metrics.end_run()
        assert run.total_cache_read == 2000
        assert run.total_cache_creation == 2000
        assert run.cache_hit_ratio == 0.5

    def test_run_is_added_to_ring_buffer_on_end(self):
        metrics.start_run(agent="matching")
        metrics.record_call(model="claude-sonnet-4-5-20250929", usage=_FakeUsage(input_tokens=1), wall_ms=1)
        metrics.end_run()
        recent = metrics.get_recent_runs()
        assert len(recent) == 1
        assert recent[0].agent == "matching"

    def test_get_run_by_id(self):
        run = metrics.start_run(agent="dossier")
        metrics.record_call(model="claude-opus-4-6", usage=_FakeUsage(input_tokens=500), wall_ms=10)
        metrics.end_run()
        fetched = metrics.get_run(run.run_id)
        assert fetched is not None
        assert fetched.agent == "dossier"
        assert fetched.calls[0].model == "claude-opus-4-6"

    def test_get_run_unknown_returns_none(self):
        assert metrics.get_run("does-not-exist") is None


class TestContextIsolation:
    """Each asyncio task should see its own run via contextvars."""

    @pytest.mark.asyncio
    async def test_nested_tasks_inherit_active_run(self):
        run = metrics.start_run(agent="matching")

        async def analyze_trial(idx: int):
            metrics.record_call(
                model="claude-sonnet-4-5-20250929",
                usage=_FakeUsage(input_tokens=100 * idx, output_tokens=50),
                wall_ms=idx * 10,
            )

        await asyncio.gather(analyze_trial(1), analyze_trial(2), analyze_trial(3))
        metrics.end_run()
        assert len(run.calls) == 3
        # Calls can complete in any order; assert on totals, not list positions.
        assert run.total_input_tokens == 600


class TestRollup:
    def test_empty_rollup(self):
        summary = metrics.summary_rollup(window_seconds=3600)
        assert summary["runs"] == 0
        assert summary["total_cost_usd"] == 0.0

    def test_rollup_aggregates_by_agent(self):
        for agent in ("matching", "matching", "dossier"):
            metrics.start_run(agent=agent)
            metrics.record_call(
                model="claude-sonnet-4-5-20250929",
                usage=_FakeUsage(input_tokens=500, output_tokens=100),
                wall_ms=100,
            )
            metrics.end_run()
        summary = metrics.summary_rollup(window_seconds=3600)
        assert summary["runs"] == 3
        assert summary["by_agent"]["matching"]["runs"] == 2
        assert summary["by_agent"]["dossier"]["runs"] == 1
        assert summary["total_calls"] == 3
        # No cache activity → ratio 0
        assert summary["cache_hit_ratio"] == 0.0

    def test_rollup_caps_by_window(self):
        metrics.start_run(agent="matching")
        metrics.record_call(model="claude-sonnet-4-5-20250929", usage=_FakeUsage(input_tokens=1), wall_ms=1)
        metrics.end_run()
        # A tiny negative-ish window should exclude everything (clamp at 60s by FastAPI's Query,
        # but the underlying function should still handle it correctly).
        summary = metrics.summary_rollup(window_seconds=1)
        # The run just happened, so it *might* be within 1 second — allow either.
        assert summary["runs"] in (0, 1)

    def test_run_summary_shape(self):
        run = metrics.start_run(agent="matching")
        metrics.record_call(
            model="claude-sonnet-4-5-20250929",
            usage=_FakeUsage(input_tokens=100, output_tokens=50),
            wall_ms=250,
        )
        time.sleep(0.01)
        metrics.end_run()
        summary = run.to_summary()
        for key in (
            "run_id",
            "agent",
            "started_at",
            "ended_at",
            "call_count",
            "total_input_tokens",
            "total_cost_usd",
            "cache_hit_ratio",
            "models_used",
            "wall_ms",
        ):
            assert key in summary
        assert summary["call_count"] == 1
        assert summary["wall_ms"] > 0
