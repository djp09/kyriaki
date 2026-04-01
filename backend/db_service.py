"""Database service layer — CRUD operations for patient profiles and match results."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from db_models import AgentEventDB, AgentTaskDB, HumanGateDB, MatchResultDB, MatchSessionDB, PatientProfileDB


async def save_patient_profile(session: AsyncSession, profile_data: dict) -> PatientProfileDB:
    """Persist a patient profile and return the ORM instance."""
    patient = PatientProfileDB(**profile_data)
    session.add(patient)
    await session.flush()
    return patient


async def save_match_session(
    session: AsyncSession,
    patient_id: UUID,
    patient_summary: str,
    total_trials_screened: int,
) -> MatchSessionDB:
    """Create a match session tied to a patient."""
    ms = MatchSessionDB(
        patient_id=patient_id,
        patient_summary=patient_summary,
        total_trials_screened=total_trials_screened,
    )
    session.add(ms)
    await session.flush()
    return ms


async def save_match_result(session: AsyncSession, session_id: UUID, match_data: dict) -> MatchResultDB:
    """Save a single trial match result."""
    mr = MatchResultDB(session_id=session_id, **match_data)
    session.add(mr)
    await session.flush()
    return mr


async def get_patient_history(session: AsyncSession, patient_id: UUID) -> list[MatchSessionDB]:
    """Retrieve all match sessions for a patient, newest first."""
    stmt = (
        select(MatchSessionDB)
        .where(MatchSessionDB.patient_id == patient_id)
        .options(selectinload(MatchSessionDB.match_results))
        .order_by(MatchSessionDB.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_match_results(session: AsyncSession, session_id: UUID) -> list[MatchResultDB]:
    """Retrieve all match results for a session, highest score first."""
    stmt = (
        select(MatchResultDB).where(MatchResultDB.session_id == session_id).order_by(MatchResultDB.match_score.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# --- Agent orchestration queries ---


async def get_task_with_gates(session: AsyncSession, task_id: UUID) -> AgentTaskDB | None:
    """Load a task with its gates eagerly loaded."""
    stmt = select(AgentTaskDB).where(AgentTaskDB.id == task_id).options(joinedload(AgentTaskDB.gates))
    result = await session.execute(stmt)
    return result.unique().scalars().first()


async def list_tasks_for_patient(session: AsyncSession, patient_id: UUID) -> list[AgentTaskDB]:
    """All tasks for a patient, newest first, with gates."""
    stmt = (
        select(AgentTaskDB)
        .where(AgentTaskDB.patient_id == patient_id)
        .options(joinedload(AgentTaskDB.gates))
        .order_by(AgentTaskDB.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.unique().scalars().all())


async def list_events_for_task(session: AsyncSession, task_id: UUID) -> list[AgentEventDB]:
    """All events for a task, oldest first (timeline order)."""
    stmt = select(AgentEventDB).where(AgentEventDB.task_id == task_id).order_by(AgentEventDB.created_at)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_gates(session: AsyncSession, status: str = "pending") -> list[HumanGateDB]:
    """Gates filtered by status, newest first."""
    stmt = select(HumanGateDB).where(HumanGateDB.status == status).order_by(HumanGateDB.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_patient_activity(session: AsyncSession, patient_id: UUID) -> list[dict]:
    """Combined timeline of tasks, events, and gates for a patient. Newest first."""
    tasks = await list_tasks_for_patient(session, patient_id)
    task_ids = [t.id for t in tasks]

    # Batch-load all events for these tasks in one query
    all_events: list[AgentEventDB] = []
    if task_ids:
        stmt = select(AgentEventDB).where(AgentEventDB.task_id.in_(task_ids)).order_by(AgentEventDB.created_at)
        result = await session.execute(stmt)
        all_events = list(result.scalars().all())

    items: list[dict] = []
    for task in tasks:
        items.append(
            {
                "type": "task",
                "timestamp": task.created_at.isoformat() if task.created_at else "",
                "data": {"task_id": str(task.id), "agent_type": task.agent_type, "status": task.status},
            }
        )
        for gate in task.gates or []:
            items.append(
                {
                    "type": "gate",
                    "timestamp": gate.created_at.isoformat() if gate.created_at else "",
                    "data": {
                        "gate_id": str(gate.id),
                        "task_id": str(gate.task_id),
                        "gate_type": gate.gate_type,
                        "status": gate.status,
                        "resolved_by": gate.resolved_by,
                    },
                }
            )

    for ev in all_events:
        items.append(
            {
                "type": "event",
                "timestamp": ev.created_at.isoformat() if ev.created_at else "",
                "data": {
                    "event_id": str(ev.id),
                    "task_id": str(ev.task_id),
                    "event_type": ev.event_type,
                    "detail": ev.data,
                },
            }
        )

    items.sort(key=lambda x: x["timestamp"], reverse=True)
    return items
