"""Database service layer — CRUD operations for patient profiles and match results."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from db_models import (
    AgentEventDB,
    AgentTaskDB,
    HumanGateDB,
    MatchResultDB,
    MatchSessionDB,
    PatientProfileDB,
    PatientProfileVersionDB,
)
from phi.audit import ACTION_READ, ACTION_WRITE, record_phi_access

_AUDIT_ACTOR_DEFAULT = "system"


def _maybe_encrypt_profile(patient: PatientProfileDB, snapshot: dict) -> None:
    """Populate the at-rest encrypted blob + hash on ``patient``.

    No-ops silently if the PHI key ring is not configured (dev/test with
    encryption disabled). See ADR-004.
    """
    try:
        from phi.keys import KeyConfigError
        from phi.profile_storage import encrypt_profile
    except ImportError:  # pragma: no cover
        return
    try:
        blob, key_id, hash_hex = encrypt_profile(snapshot)
    except KeyConfigError:
        return
    patient.profile_encrypted = blob
    patient.encryption_key_id = key_id
    patient.profile_hash = hash_hex


async def save_patient_profile(
    session: AsyncSession,
    profile_data: dict,
    *,
    actor: str = _AUDIT_ACTOR_DEFAULT,
    purpose: str | None = None,
) -> PatientProfileDB:
    """Persist a patient profile and return the ORM instance.

    Also populates the at-rest encrypted blob and emits an audit-log entry.
    """
    patient = PatientProfileDB(**profile_data)
    _maybe_encrypt_profile(patient, profile_data)
    session.add(patient)
    await session.flush()
    await record_phi_access(
        session,
        actor=actor,
        action=ACTION_WRITE,
        resource_type="patient_profile",
        resource_id=str(patient.id),
        purpose=purpose,
        metadata={"op": "create", "fields": sorted(profile_data.keys())},
    )
    return patient


def _profile_to_snapshot(patient: PatientProfileDB) -> dict:
    """Convert a PatientProfileDB to a JSON-serializable snapshot."""
    return {
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


def _diff_profiles(old: dict, new: dict) -> str:
    """Generate a human-readable summary of what changed between profiles."""
    changes = []
    for key in new:
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val != new_val:
            label = key.replace("_", " ").title()
            changes.append(f"{label}: {old_val!r} -> {new_val!r}")
    return "; ".join(changes) if changes else "No changes"


async def update_patient_profile(
    session: AsyncSession,
    patient_id: UUID,
    updates: dict,
    *,
    actor: str = _AUDIT_ACTOR_DEFAULT,
    purpose: str | None = None,
) -> PatientProfileDB | None:
    """Update a patient profile and create a version snapshot of the old state.

    Returns the updated patient, or None if not found.
    """
    patient = await session.get(PatientProfileDB, patient_id)
    if not patient:
        return None

    # Snapshot the current state before changes
    old_snapshot = _profile_to_snapshot(patient)

    # Apply updates (only fields that are present and non-None)
    for key, value in updates.items():
        if hasattr(patient, key) and key not in ("id", "created_at", "updated_at", "version"):
            setattr(patient, key, value)

    new_snapshot = _profile_to_snapshot(patient)
    change_summary = _diff_profiles(old_snapshot, new_snapshot)

    # Save version record
    session.add(
        PatientProfileVersionDB(
            patient_id=patient_id,
            version=patient.version,
            profile_snapshot=old_snapshot,
            change_summary=change_summary,
        )
    )

    # Bump version
    patient.version = patient.version + 1
    _maybe_encrypt_profile(patient, new_snapshot)
    await session.flush()
    await record_phi_access(
        session,
        actor=actor,
        action=ACTION_WRITE,
        resource_type="patient_profile",
        resource_id=str(patient_id),
        purpose=purpose,
        metadata={"op": "update", "version": patient.version, "changes": change_summary},
    )
    return patient


async def read_patient_profile(
    session: AsyncSession,
    patient_id: UUID,
    *,
    actor: str = _AUDIT_ACTOR_DEFAULT,
    purpose: str | None = None,
) -> PatientProfileDB | None:
    """Load a patient profile and emit an audit read event."""
    patient = await session.get(PatientProfileDB, patient_id)
    if patient is None:
        return None
    await record_phi_access(
        session,
        actor=actor,
        action=ACTION_READ,
        resource_type="patient_profile",
        resource_id=str(patient_id),
        purpose=purpose,
    )
    return patient


async def get_patient_versions(session: AsyncSession, patient_id: UUID) -> list[PatientProfileVersionDB]:
    """Get all version snapshots for a patient, newest first."""
    stmt = (
        select(PatientProfileVersionDB)
        .where(PatientProfileVersionDB.patient_id == patient_id)
        .order_by(PatientProfileVersionDB.version.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


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
