"""Add trial_cache table for persistent trial data caching

Revision ID: 006
Revises: 005
Create Date: 2026-04-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trial_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("cache_key", sa.String(512), nullable=False, unique=True),
        sa.Column("trials_json", JSON, nullable=False),
        sa.Column("trial_count", sa.Integer, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trial_cache_key", "trial_cache", ["cache_key"], unique=True)
    op.create_index("ix_trial_cache_expires", "trial_cache", ["expires_at"])


def downgrade() -> None:
    op.drop_table("trial_cache")
