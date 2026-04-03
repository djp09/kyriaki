"""Add composite indexes for common query patterns

Revision ID: 004
Revises: 003
Create Date: 2026-04-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Composite index for the monitor loop and task lookup queries
    # that filter by (patient_id, agent_type, status)
    op.create_index(
        "ix_task_patient_agent_status",
        "agent_tasks",
        ["patient_id", "agent_type", "status"],
    )

    # Index for outcome stats computation that groups by screening_result
    op.create_index("ix_outcome_screening_result", "trial_outcomes", ["screening_result"])

    # Index for gate lookups by gate_type (used in auto-chaining)
    op.create_index("ix_gate_type", "human_gates", ["gate_type"])


def downgrade() -> None:
    op.drop_index("ix_gate_type", table_name="human_gates")
    op.drop_index("ix_outcome_screening_result", table_name="trial_outcomes")
    op.drop_index("ix_task_patient_agent_status", table_name="agent_tasks")
