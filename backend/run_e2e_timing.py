"""E2E quality + consistency acceptance test for the matching pipeline.

Runs the standard NSCLC EGFR+ patient 3 times and asserts:
- Top 5 NCT IDs identical across all 3 runs
- Average score delta on shared trials ≤ 1.0
- Top 1 trial intervention contains an EGFR-targeted drug
- No radiation-only trial in top 10 for biomarker+ patient
- Each run completes in < 90s

Usage:
    set -a && source .env && set +a
    ../.venv/bin/python run_e2e_timing.py
"""

from __future__ import annotations

import asyncio
import sys
import time


NSCLC_PATIENT = {
    "cancer_type": "Non-Small Cell Lung Cancer",
    "cancer_stage": "Stage IV",
    "biomarkers": ["EGFR+", "PD-L1 80%"],
    "prior_treatments": ["Carboplatin/Pemetrexed", "Pembrolizumab"],
    "lines_of_therapy": 2,
    "age": 62,
    "sex": "male",
    "ecog_score": 1,
    "key_labs": None,
    "location_zip": "10001",
    "willing_to_travel_miles": 500,
    "additional_conditions": [],
    "additional_notes": None,
}

# EGFR-targeted drug names — used to assert top match is biomarker-aligned
EGFR_DRUGS = {
    "osimertinib",
    "erlotinib",
    "gefitinib",
    "afatinib",
    "amivantamab",
    "lazertinib",
    "dacomitinib",
    "egfr",  # generic mention in title
}


async def run_one(label: str, patient_data: dict) -> dict:
    """Run a single matching pipeline and return timing + results."""
    import agents as _agents  # noqa: F401

    from database import async_session, engine
    from db_models import Base
    from db_service import save_patient_profile
    from dispatcher import dispatch

    # Reset DB
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        patient = await save_patient_profile(session, patient_data)
        await session.commit()

        t0 = time.monotonic()
        task = await dispatch(
            session,
            "matching",
            patient.id,
            input_data={"max_results": 10},
        )
        await session.commit()
        elapsed = time.monotonic() - t0

        result = {
            "label": label,
            "status": task.status,
            "time_s": round(elapsed, 1),
            "error": task.error,
            "matches": [],
            "screened": 0,
            "summary": "",
        }

        if task.output_data:
            matches = task.output_data.get("matches", [])
            result["screened"] = task.output_data.get("total_trials_screened", 0)
            result["summary"] = task.output_data.get("patient_summary", "")[:80]
            result["matches"] = [
                {
                    "nct_id": m["nct_id"],
                    "score": m["match_score"],
                    "tier": m.get("match_tier", "?"),
                    "title": m["brief_title"][:55],
                    "interventions": m.get("interventions", []),
                }
                for m in matches
            ]

        return result


def print_result(r: dict) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {r['label']}")
    print(f"{'=' * 70}")
    print(f"  Status:   {r['status']}")
    print(f"  Time:     {r['time_s']}s")
    print(f"  Screened: {r['screened']}")
    print(f"  Matches:  {len(r['matches'])}")
    if r["error"]:
        print(f"  Error:    {r['error']}")
    for m in r["matches"][:10]:
        if m["score"] > 0:
            print(f"    {m['nct_id']}: score={m['score']:5.1f} [{m['tier']}] — {m['title']}")
    print(f"  Summary:  {r['summary']}...")


def assert_consistency(runs: list[dict]) -> list[str]:
    """Compare runs and return a list of failure messages."""
    failures: list[str] = []

    # Top 5 stability
    top5_lists = [[m["nct_id"] for m in r["matches"][:5]] for r in runs]
    top5_sets = [set(t) for t in top5_lists]
    if not all(s == top5_sets[0] for s in top5_sets):
        failures.append(f"Top-5 not identical across runs: {top5_lists}")

    # Score delta on shared trials
    all_shared = set.intersection(*[{m["nct_id"] for m in r["matches"]} for r in runs])
    deltas: list[float] = []
    for nct_id in all_shared:
        scores = []
        for r in runs:
            for m in r["matches"]:
                if m["nct_id"] == nct_id:
                    scores.append(m["score"])
                    break
        if len(scores) == len(runs):
            deltas.append(max(scores) - min(scores))
    avg_delta = sum(deltas) / len(deltas) if deltas else 0.0
    if avg_delta > 1.0:
        failures.append(f"Average score delta {avg_delta:.1f} > 1.0 on {len(deltas)} shared trials")

    # Top 1 must be EGFR-targeted
    for r in runs:
        if not r["matches"]:
            failures.append(f"{r['label']}: no matches at all")
            continue
        top = r["matches"][0]
        if top["score"] <= 0:
            failures.append(f"{r['label']}: top match has score 0")
            continue
        text = (top["title"] + " " + " ".join(top.get("interventions", []))).lower()
        if not any(drug in text for drug in EGFR_DRUGS):
            failures.append(
                f"{r['label']}: top match {top['nct_id']} ({top['title']}) "
                f"interventions={top.get('interventions', [])} — no EGFR drug found"
            )

    # No pure radiation in top 10
    for r in runs:
        for m in r["matches"][:10]:
            interventions = " ".join(m.get("interventions", [])).lower()
            if interventions and "radiation:" in interventions:
                # Check if there's any drug intervention too
                has_drug = "drug:" in interventions or "biological:" in interventions
                if not has_drug and m["score"] > 0:
                    failures.append(
                        f"{r['label']}: pure radiation trial {m['nct_id']} in top 10 with score {m['score']}"
                    )

    # Runtime budget
    for r in runs:
        if r["time_s"] > 90:
            failures.append(f"{r['label']}: runtime {r['time_s']}s exceeds 90s budget")

    return failures


def print_consistency_summary(runs: list[dict]) -> None:
    print(f"\n{'=' * 70}")
    print("  CONSISTENCY CHECK")
    print(f"{'=' * 70}")

    top5 = [tuple(m["nct_id"] for m in r["matches"][:5]) for r in runs]
    print("  Top 5 per run:")
    for i, t in enumerate(top5, 1):
        print(f"    Run {i}: {t}")

    all_shared = set.intersection(*[{m["nct_id"] for m in r["matches"]} for r in runs])
    print(f"\n  Shared trials across all 3 runs: {len(all_shared)}")
    deltas = []
    for nct_id in sorted(all_shared):
        scores = []
        for r in runs:
            for m in r["matches"]:
                if m["nct_id"] == nct_id:
                    scores.append(m["score"])
                    break
        if len(scores) == len(runs):
            d = max(scores) - min(scores)
            deltas.append(d)
            marker = " ✓" if d < 2 else " ⚠"
            scores_str = " / ".join(f"{s:5.1f}" for s in scores)
            print(f"    {nct_id}: {scores_str} (Δ={d:.1f}){marker}")

    if deltas:
        print(f"\n  Average score delta: {sum(deltas) / len(deltas):.2f}")
        print(f"  Max score delta:     {max(deltas):.2f}")

    runtime_str = " / ".join(f"{r['time_s']}s" for r in runs)
    print(f"\n  Runtime: {runtime_str}")


async def main() -> int:
    print("NSCLC EGFR+ Stage IV — ZIP 10001, 500 miles travel")
    print(f"Patient: {NSCLC_PATIENT['cancer_type']}, {NSCLC_PATIENT['cancer_stage']}")
    print(f"Biomarkers: {NSCLC_PATIENT['biomarkers']}")
    print(f"Prior: {NSCLC_PATIENT['prior_treatments']}")

    runs = []
    for i in range(1, 4):
        r = await run_one(f"Run {i}", NSCLC_PATIENT)
        runs.append(r)
        print_result(r)

    print_consistency_summary(runs)

    failures = assert_consistency(runs)

    print(f"\n{'=' * 70}")
    print("  ACCEPTANCE CRITERIA")
    print(f"{'=' * 70}")
    if failures:
        print("  FAILED:")
        for f in failures:
            print(f"    ✗ {f}")
        return 1
    print("  ✓ Top 5 NCT IDs identical across 3 runs")
    print("  ✓ Average score delta ≤ 1.0")
    print("  ✓ Top 1 is EGFR-targeted therapy")
    print("  ✓ No pure-radiation trial in top 10")
    print("  ✓ All runs under 90s")
    print("\n  ALL ACCEPTANCE CRITERIA PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
