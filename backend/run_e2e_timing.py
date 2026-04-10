"""E2E timing + consistency test for the matching pipeline.

Runs the standard NSCLC EGFR+ patient twice and compares results.
Usage: python3 run_e2e_timing.py
"""

import asyncio
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
                }
                for m in matches
            ]

        return result


def print_result(r: dict):
    print(f"\n{'='*70}")
    print(f"  {r['label']}")
    print(f"{'='*70}")
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


def compare_results(r1: dict, r2: dict):
    print(f"\n{'='*70}")
    print("  CONSISTENCY CHECK")
    print(f"{'='*70}")

    # Compare scored matches (score > 0)
    scored1 = {m["nct_id"]: m["score"] for m in r1["matches"] if m["score"] > 0}
    scored2 = {m["nct_id"]: m["score"] for m in r2["matches"] if m["score"] > 0}

    shared = set(scored1.keys()) & set(scored2.keys())
    only1 = set(scored1.keys()) - set(scored2.keys())
    only2 = set(scored2.keys()) - set(scored1.keys())

    print(f"  Scored trials in both runs: {len(shared)}")
    if only1:
        print(f"  Only in run 1: {only1}")
    if only2:
        print(f"  Only in run 2: {only2}")

    if shared:
        diffs = []
        for nct_id in sorted(shared):
            s1, s2 = scored1[nct_id], scored2[nct_id]
            diff = abs(s1 - s2)
            diffs.append(diff)
            marker = " ✓" if diff < 15 else " ⚠"
            print(f"    {nct_id}: {s1:5.1f} vs {s2:5.1f} (Δ={diff:.1f}){marker}")
        avg_diff = sum(diffs) / len(diffs)
        print(f"  Average score delta: {avg_diff:.1f}")
        print(f"  Max score delta:     {max(diffs):.1f}")

    # Timing
    print(f"  Run 1 time: {r1['time_s']}s")
    print(f"  Run 2 time: {r2['time_s']}s")


async def main():
    print("NSCLC EGFR+ Stage IV — ZIP 10001, 500 miles travel")
    print(f"Patient: {NSCLC_PATIENT['cancer_type']}, {NSCLC_PATIENT['cancer_stage']}")
    print(f"Biomarkers: {NSCLC_PATIENT['biomarkers']}")
    print(f"Prior: {NSCLC_PATIENT['prior_treatments']}")

    r1 = await run_one("Run 1", NSCLC_PATIENT)
    print_result(r1)

    r2 = await run_one("Run 2", NSCLC_PATIENT)
    print_result(r2)

    compare_results(r1, r2)


if __name__ == "__main__":
    asyncio.run(main())
