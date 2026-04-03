"""Add patient profile versioning

Revision ID: 007
Revises: 006
Create Date: 2026-04-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add version column to patient_profiles
    op.add_column("patient_profiles", sa.Column("version", sa.Integer, server_default="1", nullable=False))

    # Create versions table
    op.create_table(
        "patient_profile_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patient_profiles.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("profile_snapshot", JSON, nullable=False),
        sa.Column("change_summary", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_profile_version_patient", "patient_profile_versions", ["patient_id"])
    op.create_index("ix_profile_version_number", "patient_profile_versions", ["patient_id", "version"], unique=True)


def downgrade() -> None:
    op.drop_table("patient_profile_versions")
    op.drop_column("patient_profiles", "version")
