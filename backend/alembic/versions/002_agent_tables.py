"""Agent orchestration tables: agent_tasks, agent_events, human_gates

Revision ID: 002
Revises: 001
Create Date: 2026-04-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patient_profiles.id"), nullable=False),
        sa.Column("input_data", JSON, server_default="{}"),
        sa.Column("output_data", JSON, nullable=True),
        sa.Column("parent_task_id", UUID(as_uuid=True), sa.ForeignKey("agent_tasks.id"), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_task_status", "agent_tasks", ["status"])
    op.create_index("ix_task_agent_type", "agent_tasks", ["agent_type"])
    op.create_index("ix_task_patient_id", "agent_tasks", ["patient_id"])
    op.create_index("ix_task_created_at", "agent_tasks", ["created_at"])

    op.create_table(
        "agent_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("agent_tasks.id"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("data", JSON, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_event_task_id", "agent_events", ["task_id"])
    op.create_index("ix_event_created_at", "agent_events", ["created_at"])

    op.create_table(
        "human_gates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("agent_tasks.id"), nullable=False),
        sa.Column("gate_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("requested_data", JSON, server_default="{}"),
        sa.Column("resolution_data", JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(256), nullable=True),
    )
    op.create_index("ix_gate_task_id", "human_gates", ["task_id"])
    op.create_index("ix_gate_status", "human_gates", ["status"])


def downgrade() -> None:
    op.drop_table("human_gates")
    op.drop_table("agent_events")
    op.drop_table("agent_tasks")
