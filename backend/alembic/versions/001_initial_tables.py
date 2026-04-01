"""Initial tables: patient_profiles, match_sessions, match_results

Revision ID: 001
Revises: None
Create Date: 2026-03-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "patient_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("cancer_type", sa.String(256), nullable=False),
        sa.Column("cancer_stage", sa.String(64), nullable=False),
        sa.Column("biomarkers", JSON, server_default="[]"),
        sa.Column("prior_treatments", JSON, server_default="[]"),
        sa.Column("lines_of_therapy", sa.Integer, server_default="0"),
        sa.Column("age", sa.Integer, nullable=False),
        sa.Column("sex", sa.String(16), nullable=False),
        sa.Column("ecog_score", sa.Integer, nullable=True),
        sa.Column("key_labs", JSON, nullable=True),
        sa.Column("location_zip", sa.String(10), nullable=False),
        sa.Column("willing_to_travel_miles", sa.Integer, server_default="50"),
        sa.Column("additional_conditions", JSON, server_default="[]"),
        sa.Column("additional_notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_patient_cancer_type", "patient_profiles", ["cancer_type"])
    op.create_index("ix_patient_created_at", "patient_profiles", ["created_at"])

    op.create_table(
        "match_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patient_profiles.id"), nullable=False),
        sa.Column("patient_summary", sa.Text, server_default=""),
        sa.Column("total_trials_screened", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_session_patient_id", "match_sessions", ["patient_id"])
    op.create_index("ix_session_created_at", "match_sessions", ["created_at"])

    op.create_table(
        "match_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("match_sessions.id"), nullable=False),
        sa.Column("nct_id", sa.String(32), nullable=False),
        sa.Column("brief_title", sa.Text, server_default=""),
        sa.Column("phase", sa.String(64), server_default=""),
        sa.Column("match_score", sa.Integer, server_default="0"),
        sa.Column("match_explanation", sa.Text, server_default=""),
        sa.Column("inclusion_evaluations", JSON, server_default="[]"),
        sa.Column("exclusion_evaluations", JSON, server_default="[]"),
        sa.Column("flags_for_oncologist", JSON, server_default="[]"),
        sa.Column("nearest_site", JSON, nullable=True),
        sa.Column("distance_miles", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_result_session_id", "match_results", ["session_id"])
    op.create_index("ix_result_nct_id", "match_results", ["nct_id"])
    op.create_index("ix_result_match_score", "match_results", ["match_score"])
    op.create_index("ix_result_created_at", "match_results", ["created_at"])


def downgrade() -> None:
    op.drop_table("match_results")
    op.drop_table("match_sessions")
    op.drop_table("patient_profiles")
