"""End-to-end integration test for the agent orchestration layer.

Uses SQLite in-memory (no Postgres required), real ClinicalTrials.gov API,
and real Claude API. Run with: python3 test_integration_e2e.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

# Patch database before any other imports so all modules use the test DB
import database

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
_test_session_factory = async_sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)

# Override the module-level engine and session factory
database.engine = _test_engine
database.async_session = _test_session_factory

# Now import everything else (they'll use the patched database module)
from db_models import (  # noqa: E402
    AgentEventDB,
    AgentTaskDB,
    Base,
    HumanGateDB,
    PatientProfileDB,
    TaskStatus,
)
from dispatcher import dispatch  # noqa: E402

import agents as _agents  # noqa: E402, F401 — triggers registration


async def setup_db():
    """Create all tables in the in-memory SQLite DB."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[OK] In-memory SQLite database created with all tables")


async def create_test_patient(session: AsyncSession) -> PatientProfileDB:
    """Insert a test patient profile."""
    patient = PatientProfileDB(
        id=uuid.uuid4(),
        cancer_type="Non-Small Cell Lung Cancer",
        cancer_stage="Stage IV",
        biomarkers=["EGFR+", "PD-L1 80%", "ALK-"],
        prior_treatments=["Carboplatin/Pemetrexed", "Pembrolizumab"],
        lines_of_therapy=2,
        age=62,
        sex="male",
        ecog_score=1,
        key_labs={"wbc": 5.2, "platelets": 180},
        location_zip="10001",
        willing_to_travel_miles=100,
        additional_conditions=["Type 2 Diabetes"],
        additional_notes="Previously responded well to immunotherapy",
    )
    session.add(patient)
    await session.flush()
    print(f"[OK] Test patient created: {patient.id}")
    return patient


async def test_matching_agent(session: AsyncSession, patient: PatientProfileDB) -> AgentTaskDB:
    """Run the MatchingAgent through the dispatcher."""
    print("\n--- STEP 1: MatchingAgent ---")
    print("Dispatching matching task (this calls ClinicalTrials.gov + Claude)...")

    patient_data = {
        "cancer_type": patient.cancer_type,
        "cancer_stage": patient.cancer_stage,
        "biomarkers": patient.biomarkers,
        "prior_treatments": patient.prior_treatments,
        "lines_of_therapy": patient.lines_of_therapy,
        "age": patient.age,
        "sex": patient.sex,
        "ecog_score": patient.ecog_score,
        "key_labs": patient.key_labs,
        "location_zip": patient.location_zip,
        "willing_to_travel_miles": patient.willing_to_travel_miles,
        "additional_conditions": patient.additional_conditions,
        "additional_notes": patient.additional_notes,
    }

    task = await dispatch(
        session,
        "matching",
        patient.id,
        input_data={"patient": patient_data, "max_results": 3},
    )

    print(f"  Task ID:    {task.id}")
    print(f"  Status:     {task.status}")
    print(f"  Agent:      {task.agent_type}")
    print(f"  Started:    {task.started_at}")
    print(f"  Completed:  {task.completed_at}")

    if task.status == TaskStatus.failed.value:
        print(f"  ERROR:      {task.error}")
        return task

    if task.output_data:
        print(f"  Trials screened: {task.output_data.get('total_trials_screened', '?')}")
        matches = task.output_data.get("matches", [])
        print(f"  Matches found:   {len(matches)}")
        print(f"  Patient summary: {task.output_data.get('patient_summary', '')[:120]}...")
        for i, m in enumerate(matches):
            print(f"    [{i + 1}] {m['nct_id']} — score {m.get('match_score', '?')}: {m['brief_title'][:70]}")

        # Token tracking validation
        token_usage = task.output_data.get("token_usage")
        if token_usage:
            print(
                f"  Token usage:  {token_usage['input_tokens']} in / {token_usage['output_tokens']} out / {token_usage['total_tokens']} total"
            )
        else:
            print("  Token usage:  NOT TRACKED (unexpected)")

    # Check events
    events = [obj for obj in session.new | session.dirty if isinstance(obj, AgentEventDB)]
    # Query instead since objects were already flushed
    from sqlalchemy import select

    result = await session.execute(
        select(AgentEventDB).where(AgentEventDB.task_id == task.id).order_by(AgentEventDB.created_at)
    )
    events = list(result.scalars().all())
    print(f"  Events:     {[e.event_type for e in events]}")

    assert task.status == TaskStatus.completed.value, f"Expected completed, got {task.status}"
    assert task.output_data is not None
    assert len(task.output_data.get("matches", [])) > 0, "Expected at least 1 match"
    print("[OK] MatchingAgent completed successfully")
    return task


async def test_dossier_agent(
    session: AsyncSession, patient: PatientProfileDB, matching_task: AgentTaskDB
) -> AgentTaskDB:
    """Run the DossierAgent through the dispatcher for a specific trial."""
    print("\n--- STEP 2: DossierAgent (per-trial) ---")
    matches = matching_task.output_data.get("matches", [])
    target_match = matches[0]  # Analyze the top match
    nct_id = target_match["nct_id"]
    print(f"Dispatching dossier for {nct_id}: {target_match['brief_title'][:60]}...")

    task = await dispatch(
        session,
        "dossier",
        patient.id,
        input_data={
            "patient": matching_task.input_data["patient"],
            "match": target_match,
            "nct_id": nct_id,
            "patient_summary": matching_task.output_data.get("patient_summary", ""),
        },
        parent_task_id=matching_task.id,
    )

    print(f"  Task ID:    {task.id}")
    print(f"  Status:     {task.status}")
    print(f"  Parent:     {task.parent_task_id}")
    print(f"  Started:    {task.started_at}")

    if task.status == TaskStatus.failed.value:
        print(f"  ERROR:      {task.error}")
        return task

    if task.output_data and "dossier" in task.output_data:
        dossier = task.output_data["dossier"]
        print(f"  Dossier generated at: {dossier.get('generated_at', '?')}")
        print(f"  Dossier nct_id: {dossier.get('nct_id', 'MISSING')}")
        print(f"  Sections: {len(dossier.get('sections', []))}")
        for section in dossier.get("sections", []):
            print(f"    Trial: {section.get('nct_id')} — {section.get('brief_title', '')[:60]}")
            if "revised_score" in section:
                print(f"    Revised score: {section['revised_score']}")
                print(f"    Justification: {section.get('score_justification', '')[:100]}...")
            if "analysis_error" in section:
                print(f"    Analysis error: {section['analysis_error']}")

        # Token tracking validation
        token_usage = task.output_data.get("token_usage")
        if token_usage:
            print(
                f"  Token usage:  {token_usage['input_tokens']} in / {token_usage['output_tokens']} out / {token_usage['total_tokens']} total"
            )
        else:
            print("  Token usage:  NOT TRACKED (unexpected)")

    # Check for human gate
    from sqlalchemy import select

    result = await session.execute(select(HumanGateDB).where(HumanGateDB.task_id == task.id))
    gates = list(result.scalars().all())

    if gates:
        gate = gates[0]
        print(f"\n  Human gate created:")
        print(f"    Gate ID:   {gate.id}")
        print(f"    Type:      {gate.gate_type}")
        print(f"    Status:    {gate.status}")

    assert task.status == TaskStatus.blocked.value, f"Expected blocked (waiting for gate), got {task.status}"
    assert len(gates) == 1, "Expected exactly 1 human gate"
    print("[OK] DossierAgent blocked on human gate as expected")
    return task


async def test_gate_resolution(session: AsyncSession, dossier_task: AgentTaskDB):
    """Resolve the human gate to complete the dossier task."""
    print("\n--- STEP 3: Gate Resolution ---")

    from sqlalchemy import select

    result = await session.execute(select(HumanGateDB).where(HumanGateDB.task_id == dossier_task.id))
    gate = result.scalars().first()
    assert gate is not None, "No gate found"

    # Approve the gate
    gate.status = "approved"
    gate.resolved_by = "dr.smith@hospital.org"
    gate.resolution_data = {"notes": "Reviewed and approved for patient outreach"}
    gate.resolved_at = datetime.now(timezone.utc)

    # Update the task
    dossier_task.status = TaskStatus.completed.value
    dossier_task.completed_at = datetime.now(timezone.utc)
    await session.flush()

    print(f"  Gate resolved: approved by {gate.resolved_by}")
    print(f"  Task status:   {dossier_task.status}")
    print(f"  Completed at:  {dossier_task.completed_at}")

    assert dossier_task.status == TaskStatus.completed.value
    assert gate.status == "approved"
    print("[OK] Gate resolved, dossier task completed")


async def run_all():
    """Run the full end-to-end integration test."""
    print("=" * 60)
    print("KYRIAKI E2E INTEGRATION TEST")
    print("ClinicalTrials.gov (real) + Claude API (real) + SQLite")
    print("=" * 60)

    await setup_db()

    async with _test_session_factory() as session:
        try:
            patient = await create_test_patient(session)

            # Step 1: Matching
            matching_task = await test_matching_agent(session, patient)
            if matching_task.status == TaskStatus.failed.value:
                print("\n[FAIL] Matching failed — cannot continue to dossier")
                await session.commit()
                return False

            # Step 2: Dossier
            dossier_task = await test_dossier_agent(session, patient, matching_task)
            if dossier_task.status == TaskStatus.failed.value:
                print("\n[FAIL] Dossier failed — cannot continue to gate resolution")
                await session.commit()
                return False

            # Step 3: Gate resolution
            await test_gate_resolution(session, dossier_task)

            await session.commit()

            print("\n" + "=" * 60)
            print("ALL STEPS PASSED")
            print("=" * 60)
            print(f"\nFull pipeline: Patient → MatchingAgent → DossierAgent → Human Gate → Approved")
            return True

        except Exception as e:
            await session.rollback()
            print(f"\n[FAIL] Unhandled exception: {type(e).__name__}: {e}")
            import traceback

            traceback.print_exc()
            return False


if __name__ == "__main__":
    success = asyncio.run(run_all())
    sys.exit(0 if success else 1)
