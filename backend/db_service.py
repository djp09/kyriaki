"""Database service layer — CRUD operations for patient profiles and match results."""

from typing import Dict, List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models import MatchResultDB, MatchSessionDB, PatientProfileDB


async def save_patient_profile(session: AsyncSession, profile_data: Dict) -> PatientProfileDB:
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


async def save_match_result(session: AsyncSession, session_id: UUID, match_data: Dict) -> MatchResultDB:
    """Save a single trial match result."""
    mr = MatchResultDB(session_id=session_id, **match_data)
    session.add(mr)
    await session.flush()
    return mr


async def get_patient_history(session: AsyncSession, patient_id: UUID) -> List[MatchSessionDB]:
    """Retrieve all match sessions for a patient, newest first."""
    stmt = (
        select(MatchSessionDB)
        .where(MatchSessionDB.patient_id == patient_id)
        .options(selectinload(MatchSessionDB.match_results))
        .order_by(MatchSessionDB.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_match_results(session: AsyncSession, session_id: UUID) -> List[MatchResultDB]:
    """Retrieve all match results for a session, highest score first."""
    stmt = (
        select(MatchResultDB)
        .where(MatchResultDB.session_id == session_id)
        .order_by(MatchResultDB.match_score.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
