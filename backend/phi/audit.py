"""Append-only hash-chained audit log for PHI access.

Writing
-------
Call ``record_phi_access`` inside a DB transaction whenever patient data
is read, written, or exported. The function:

1. Locks and reads the tail row (``SELECT ... FOR UPDATE`` on Postgres,
   serialised by WAL on SQLite).
2. Computes this row's ``row_hash`` as
   ``sha256(prev_hash || canonical_fields_json)``.
3. Inserts the new row.

Because each hash depends on its predecessor, any row that is later
mutated or removed breaks the chain at that point and is detectable by
``scripts/verify-audit-chain.py``.

Contents
--------
The audit row records *the fact that* a PHI resource was accessed — it
does NOT record the PHI payload itself. ``metadata`` may include
non-PHI context (count of records, field list, purpose) but callers are
responsible for ensuring they do not include identifiers in metadata.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db_models import AuditLogDB

# Actions emitted by callers. Extendable, but keep the set small and explicit.
ACTION_READ = "read"
ACTION_WRITE = "write"
ACTION_EXPORT = "export"
ACTION_DELETE = "delete"
ACTION_LOGIN = "login"
ACTION_EXTERNAL_LLM_CALL = "external_llm_call"

_ALLOWED_ACTIONS = frozenset(
    {ACTION_READ, ACTION_WRITE, ACTION_EXPORT, ACTION_DELETE, ACTION_LOGIN, ACTION_EXTERNAL_LLM_CALL}
)


def compute_row_hash(
    *,
    occurred_at: datetime,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str | None,
    purpose: str | None,
    metadata: Mapping[str, Any] | None,
    prev_hash: str | None,
) -> str:
    """Compute the deterministic SHA-256 row hash.

    The same inputs produce the same hash; this is also the function used
    by the chain verifier script.
    """
    # Normalise datetime to UTC. SQLite drops tzinfo on reload, so we
    # treat naive datetimes as UTC (which is how record_phi_access writes
    # them) to keep the hash stable across write/read roundtrips.
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    else:
        occurred_at = occurred_at.astimezone(timezone.utc)

    # Serialise the fields in a canonical order. We *exclude* the row id
    # because the hash should not depend on the auto-assigned id.
    canonical = json.dumps(
        {
            "prev_hash": prev_hash or "",
            "occurred_at": occurred_at.isoformat(),
            "actor": actor,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id or "",
            "purpose": purpose or "",
            "metadata": metadata or {},
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _tail_hash(session: AsyncSession) -> str | None:
    """Return the row_hash of the most recent entry (locked if supported)."""
    # Try to grab a row-level lock on the tail to serialise writers on
    # Postgres. SQLite does not support FOR UPDATE — it serialises writers
    # via the database-level write lock anyway.
    dialect = session.bind.dialect.name if session.bind is not None else ""
    if dialect == "postgresql":
        result = await session.execute(text("SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1 FOR UPDATE"))
        row = result.first()
        return row[0] if row else None

    stmt = select(AuditLogDB.row_hash).order_by(AuditLogDB.id.desc()).limit(1)
    result = await session.execute(stmt)
    row = result.first()
    return row[0] if row else None


async def record_phi_access(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    purpose: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> AuditLogDB:
    """Append an audit log entry for a PHI access.

    Must be called within an open transaction on ``session``. The caller
    commits or rolls back.

    Raises ``ValueError`` on malformed input.
    """
    if action not in _ALLOWED_ACTIONS:
        raise ValueError(f"Unknown audit action: {action!r}")
    if not actor:
        raise ValueError("actor is required")
    if not resource_type:
        raise ValueError("resource_type is required")

    when = (occurred_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    prev_hash = await _tail_hash(session)
    row_hash = compute_row_hash(
        occurred_at=when,
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        purpose=purpose,
        metadata=metadata,
        prev_hash=prev_hash,
    )
    entry = AuditLogDB(
        occurred_at=when,
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        purpose=purpose,
        meta=dict(metadata) if metadata else None,
        prev_hash=prev_hash,
        row_hash=row_hash,
    )
    session.add(entry)
    await session.flush()
    return entry


async def verify_chain(session: AsyncSession) -> tuple[bool, list[str]]:
    """Replay the chain and return (ok, list_of_error_messages).

    Each row's hash is recomputed from its fields plus the previous row's
    hash. Any discrepancy (bad hash, broken link, missing predecessor) is
    reported with the offending row id.
    """
    stmt = select(AuditLogDB).order_by(AuditLogDB.id.asc())
    result = await session.execute(stmt)
    errors: list[str] = []
    expected_prev: str | None = None
    for row in result.scalars():
        if (row.prev_hash or None) != expected_prev:
            errors.append(f"row {row.id}: prev_hash={row.prev_hash!r} expected {expected_prev!r}")
        recomputed = compute_row_hash(
            occurred_at=row.occurred_at,
            actor=row.actor,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            purpose=row.purpose,
            metadata=row.meta,
            prev_hash=row.prev_hash,
        )
        if recomputed != row.row_hash:
            errors.append(f"row {row.id}: row_hash mismatch (stored={row.row_hash}, recomputed={recomputed})")
        expected_prev = row.row_hash
    return (not errors), errors
