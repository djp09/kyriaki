"""Quick E2E timing test for the matching pipeline with prompt caching."""

import asyncio
import time


async def run():
    import agents as _agents  # noqa: F401 — triggers registration

    from database import async_session, engine
    from db_models import Base
    from db_service import save_patient_profile
    from dispatcher import dispatch

    # Reset DB
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    patient_data = {
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
        "willing_to_travel_miles": 100,
        "additional_conditions": [],
        "additional_notes": None,
    }

    async with async_session() as session:
        patient = await save_patient_profile(session, patient_data)
        await session.commit()
        print(f"Patient saved: {patient.id}")

        start = time.monotonic()
        task = await dispatch(
            session,
            "matching",
            patient.id,
            input_data={"max_results": 5},
        )
        await session.commit()
        elapsed = time.monotonic() - start

        print(f"Status:   {task.status}")
        print(f"Time:     {elapsed:.1f}s")

        if task.output_data:
            matches = task.output_data.get("matches", [])
            screened = task.output_data.get("total_trials_screened", 0)
            print(f"Matches:  {len(matches)}")
            print(f"Screened: {screened}")
            for m in matches[:5]:
                score = m["match_score"]
                title = m["brief_title"][:60]
                print(f"  {m['nct_id']}: score={score} — {title}")
            summary = task.output_data.get("patient_summary", "")[:100]
            print(f"Summary:  {summary}...")
        else:
            print(f"Error:    {task.error}")


if __name__ == "__main__":
    asyncio.run(run())
