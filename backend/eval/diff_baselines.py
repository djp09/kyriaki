"""Compare two eval baseline JSON files side-by-side.

Usage:
    python -m eval.diff_baselines eval/baselines/2026-04-11-quick.json \
                                  eval/baselines/2026-04-12-quick.json

Reports cost / wall / cache / quality deltas. Exits non-zero if a quality
metric regresses beyond the configured threshold (mean score drift > 5pp).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _load(path: str | Path) -> dict:
    with Path(path).open() as f:
        return json.load(f)


def _format_delta(label: str, before: float, after: float, *, fmt: str = ".2f", as_pct: bool = False) -> str:
    delta = after - before
    if as_pct and before != 0:
        pct = delta / before * 100
        return f"  {label:30s} {before:>10{fmt}} → {after:>10{fmt}}  ({delta:+{fmt}} / {pct:+.1f}%)"
    return f"  {label:30s} {before:>10{fmt}} → {after:>10{fmt}}  ({delta:+{fmt}})"


def diff(baseline_path: str, current_path: str) -> int:
    baseline = _load(baseline_path)
    current = _load(current_path)

    b = baseline.get("totals", {})
    c = current.get("totals", {})

    print(f"Baseline: {baseline_path}")
    print(f"  run_at:  {baseline.get('run_at')}")
    print(f"  patients: {baseline.get('patients')}")
    print()
    print(f"Current:  {current_path}")
    print(f"  run_at:  {current.get('run_at')}")
    print(f"  patients: {current.get('patients')}")
    print()

    print("=" * 75)
    print("COST")
    print("=" * 75)
    print(
        _format_delta("total_cost_usd", b.get("total_cost_usd", 0), c.get("total_cost_usd", 0), fmt=".4f", as_pct=True)
    )
    print(
        _format_delta(
            "avg_cost_per_patient_usd",
            b.get("avg_cost_per_patient_usd", 0),
            c.get("avg_cost_per_patient_usd", 0),
            fmt=".4f",
            as_pct=True,
        )
    )
    print(
        _format_delta("total_claude_calls", b.get("total_claude_calls", 0), c.get("total_claude_calls", 0), fmt=".0f")
    )
    print(
        _format_delta("total_input_tokens", b.get("total_input_tokens", 0), c.get("total_input_tokens", 0), fmt=".0f")
    )
    print(
        _format_delta(
            "total_output_tokens", b.get("total_output_tokens", 0), c.get("total_output_tokens", 0), fmt=".0f"
        )
    )

    print()
    print("=" * 75)
    print("PERFORMANCE")
    print("=" * 75)
    print(
        _format_delta(
            "avg_wall_ms_per_patient",
            b.get("avg_wall_ms_per_patient", 0),
            c.get("avg_wall_ms_per_patient", 0),
            fmt=".0f",
            as_pct=True,
        )
    )
    print(
        _format_delta(
            "avg_cache_hit_ratio",
            b.get("avg_cache_hit_ratio", 0) * 100,
            c.get("avg_cache_hit_ratio", 0) * 100,
            fmt=".1f",
        )
        + "  (% points)"
    )

    print()
    print("=" * 75)
    print("QUALITY")
    print("=" * 75)
    print(_format_delta("score_mean", b.get("score_mean", 0), c.get("score_mean", 0), fmt=".1f"))
    print(_format_delta("score_median", b.get("score_median", 0), c.get("score_median", 0), fmt=".1f"))
    print(_format_delta("score_stdev", b.get("score_stdev", 0), c.get("score_stdev", 0), fmt=".1f"))
    print(_format_delta("score_count", b.get("score_count", 0), c.get("score_count", 0), fmt=".0f"))

    # Quality regression gate: mean score drift > 5pp is a fail
    score_drift = abs(c.get("score_mean", 0) - b.get("score_mean", 0))
    print()
    print("=" * 75)
    if score_drift > 5.0:
        print(f"FAIL: score_mean drifted {score_drift:.1f} pp (threshold 5.0)")
        return 1
    print(f"PASS: score_mean drift {score_drift:.1f} pp <= 5.0 threshold")
    return 0


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python -m eval.diff_baselines <baseline.json> <current.json>")
        return 2
    return diff(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    sys.exit(main())
