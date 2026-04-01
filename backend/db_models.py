"""SQLAlchemy ORM models for persistent storage."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class PatientProfileDB(Base):
    __tablename__ = "patient_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    cancer_type: Mapped[str] = mapped_column(String(256), nullable=False)
    cancer_stage: Mapped[str] = mapped_column(String(64), nullable=False)
    biomarkers: Mapped[list] = mapped_column(JSON, default=list)
    prior_treatments: Mapped[list] = mapped_column(JSON, default=list)
    lines_of_therapy: Mapped[int] = mapped_column(Integer, default=0)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    sex: Mapped[str] = mapped_column(String(16), nullable=False)
    ecog_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    key_labs: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    location_zip: Mapped[str] = mapped_column(String(10), nullable=False)
    willing_to_travel_miles: Mapped[int] = mapped_column(Integer, default=50)
    additional_conditions: Mapped[list] = mapped_column(JSON, default=list)
    additional_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    match_sessions: Mapped[list[MatchSessionDB]] = relationship(back_populates="patient", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_patient_cancer_type", "cancer_type"),
        Index("ix_patient_created_at", "created_at"),
    )


class MatchSessionDB(Base):
    __tablename__ = "match_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patient_profiles.id"), nullable=False)
    patient_summary: Mapped[str] = mapped_column(Text, default="")
    total_trials_screened: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    patient: Mapped[PatientProfileDB] = relationship(back_populates="match_sessions")
    match_results: Mapped[list[MatchResultDB]] = relationship(back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_session_patient_id", "patient_id"),
        Index("ix_session_created_at", "created_at"),
    )


class MatchResultDB(Base):
    __tablename__ = "match_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("match_sessions.id"), nullable=False)
    nct_id: Mapped[str] = mapped_column(String(32), nullable=False)
    brief_title: Mapped[str] = mapped_column(Text, default="")
    phase: Mapped[str] = mapped_column(String(64), default="")
    match_score: Mapped[int] = mapped_column(Integer, default=0)
    match_explanation: Mapped[str] = mapped_column(Text, default="")
    inclusion_evaluations: Mapped[list] = mapped_column(JSON, default=list)
    exclusion_evaluations: Mapped[list] = mapped_column(JSON, default=list)
    flags_for_oncologist: Mapped[list] = mapped_column(JSON, default=list)
    nearest_site: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    distance_miles: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped[MatchSessionDB] = relationship(back_populates="match_results")

    __table_args__ = (
        Index("ix_result_session_id", "session_id"),
        Index("ix_result_nct_id", "nct_id"),
        Index("ix_result_match_score", "match_score"),
        Index("ix_result_created_at", "created_at"),
    )


# --- Agent orchestration models ---


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    blocked = "blocked"


class GateStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class AgentTaskDB(Base):
    __tablename__ = "agent_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    agent_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=TaskStatus.pending.value)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patient_profiles.id"), nullable=False)
    input_data: Mapped[dict] = mapped_column(JSON, default=dict)
    output_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    parent_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_tasks.id"), nullable=True
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list[AgentEventDB]] = relationship(back_populates="task", cascade="all, delete-orphan")
    gates: Mapped[list[HumanGateDB]] = relationship(back_populates="task", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_task_status", "status"),
        Index("ix_task_agent_type", "agent_type"),
        Index("ix_task_patient_id", "patient_id"),
        Index("ix_task_created_at", "created_at"),
    )


class AgentEventDB(Base):
    __tablename__ = "agent_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_tasks.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    task: Mapped[AgentTaskDB] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_event_task_id", "task_id"),
        Index("ix_event_created_at", "created_at"),
    )


class HumanGateDB(Base):
    __tablename__ = "human_gates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_tasks.id"), nullable=False)
    gate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=GateStatus.pending.value)
    requested_data: Mapped[dict] = mapped_column(JSON, default=dict)
    resolution_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    task: Mapped[AgentTaskDB] = relationship(back_populates="gates")

    __table_args__ = (
        Index("ix_gate_task_id", "task_id"),
        Index("ix_gate_status", "status"),
    )


class TrialWatchDB(Base):
    __tablename__ = "trial_watches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patient_profiles.id"), nullable=False)
    nct_id: Mapped[str] = mapped_column(String(32), nullable=False)
    last_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_site_count: Mapped[int] = mapped_column(Integer, default=0)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (Index("ix_watch_patient_id", "patient_id"),)
