"""Trial watches table for Monitor Agent

Revision ID: 003
Revises: 002
Create Date: 2026-04-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trial_watches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patient_profiles.id"), nullable=False),
        sa.Column("nct_id", sa.String(32), nullable=False),
        sa.Column("last_status", sa.String(64), nullable=True),
        sa.Column("last_site_count", sa.Integer, server_default="0"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_watch_patient_id", "trial_watches", ["patient_id"])


def downgrade() -> None:
    op.drop_table("trial_watches")
