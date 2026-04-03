"""Add patient_pipelines table and trial_watches unique constraint

Revision ID: 005
Revises: 004
Create Date: 2026-04-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "patient_pipelines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patient_profiles.id"), nullable=False, unique=True),
        sa.Column("current_stage", sa.String(32), nullable=False, server_default="matching"),
        sa.Column("current_task_id", UUID(as_uuid=True), sa.ForeignKey("agent_tasks.id"), nullable=True),
        sa.Column("blocked_at_gate_id", UUID(as_uuid=True), sa.ForeignKey("human_gates.id"), nullable=True),
        sa.Column("last_completed_stage", sa.String(32), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_pipeline_patient_id", "patient_pipelines", ["patient_id"], unique=True)
    op.create_index("ix_pipeline_stage", "patient_pipelines", ["current_stage"])

    # Add unique constraint on trial_watches (patient_id, nct_id)
    op.create_index("ix_watch_patient_nct", "trial_watches", ["patient_id", "nct_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_watch_patient_nct", table_name="trial_watches")
    op.drop_table("patient_pipelines")
