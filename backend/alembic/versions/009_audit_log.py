"""Add append-only hash-chained audit log

Creates ``audit_log`` for every PHI access event. Hash chain enforced
in application code (see ``phi.audit.AuditLogger``) and verified by
``scripts/verify-audit-chain.py``.

Revision ID: 009
Revises: 008
Create Date: 2026-04-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(256), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=True),
        sa.Column("purpose", sa.String(256), nullable=True),
        sa.Column("metadata", JSON, nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=True),
        sa.Column("row_hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_occurred_at", "audit_log", ["occurred_at"])
    op.create_index("ix_audit_actor", "audit_log", ["actor"])
    op.create_index("ix_audit_resource", "audit_log", ["resource_type", "resource_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_resource", "audit_log")
    op.drop_index("ix_audit_actor", "audit_log")
    op.drop_index("ix_audit_occurred_at", "audit_log")
    op.drop_table("audit_log")
