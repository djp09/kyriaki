"""Add summary_embedding and structured_criteria columns to trial_cache.

ADR-002 Stage 3 (semantic recall) and Stage 4 (criterion extraction cache).

The summary_embedding column stores Gemma-generated embeddings for
cosine-similarity recall. structured_criteria caches Stage 4 output
so extraction only runs when eligibility text changes.

For SQLite dev: vector columns are stored as JSON (list of floats).
For Postgres prod: use pgvector's vector(768) type.

Revision ID: 010
Revises: 009
Create Date: 2026-04-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # summary_embedding: 768-dim vector from Gemma nomic-embed-text.
    # Stored as JSON array in SQLite dev; pgvector in Postgres prod.
    op.add_column("trial_cache", sa.Column("summary_embedding", JSON, nullable=True))

    # structured_criteria: cached Stage 4 output (list of criterion dicts).
    op.add_column("trial_cache", sa.Column("structured_criteria", JSON, nullable=True))

    # eligibility_text_hash: SHA-256 of raw eligibility text, used to detect
    # when re-extraction is needed.
    op.add_column("trial_cache", sa.Column("eligibility_text_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("trial_cache", "eligibility_text_hash")
    op.drop_column("trial_cache", "structured_criteria")
    op.drop_column("trial_cache", "summary_embedding")
