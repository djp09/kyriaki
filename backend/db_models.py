"""SQLAlchemy ORM models for persistent storage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


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
    ecog_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    key_labs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    location_zip: Mapped[str] = mapped_column(String(10), nullable=False)
    willing_to_travel_miles: Mapped[int] = mapped_column(Integer, default=50)
    additional_conditions: Mapped[list] = mapped_column(JSON, default=list)
    additional_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    nearest_site: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    distance_miles: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped[MatchSessionDB] = relationship(back_populates="match_results")

    __table_args__ = (
        Index("ix_result_session_id", "session_id"),
        Index("ix_result_nct_id", "nct_id"),
        Index("ix_result_match_score", "match_score"),
        Index("ix_result_created_at", "created_at"),
    )
