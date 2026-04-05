"""Add at-rest encrypted patient-profile blob

Adds a ``profile_encrypted`` bytea column alongside the existing plaintext
columns on ``patient_profiles``. This is the additive path from ADR-004:
existing read sites keep working against the plaintext columns while new
write sites maintain the encrypted blob. A follow-up migration will drop
the plaintext columns once all callers are cut over.

Revision ID: 008
Revises: 007
Create Date: 2026-04-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "patient_profiles",
        sa.Column("profile_encrypted", sa.LargeBinary, nullable=True),
    )
    op.add_column(
        "patient_profiles",
        sa.Column("encryption_key_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "patient_profiles",
        sa.Column("profile_hash", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("patient_profiles", "profile_hash")
    op.drop_column("patient_profiles", "encryption_key_id")
    op.drop_column("patient_profiles", "profile_encrypted")
