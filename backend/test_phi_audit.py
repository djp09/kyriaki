"""Tests for phi.audit — append-only hash-chained audit log."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base
from db_models import AuditLogDB  # noqa: F401 — ensure model is registered
from phi.audit import (
    ACTION_EXTERNAL_LLM_CALL,
    ACTION_READ,
    ACTION_WRITE,
    compute_row_hash,
    record_phi_access,
    verify_chain,
)


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_single_entry_writes_hash(session: AsyncSession) -> None:
    entry = await record_phi_access(
        session,
        actor="alice@clinic",
        action=ACTION_READ,
        resource_type="patient_profile",
        resource_id="patient-42",
        purpose="matching_session",
    )
    assert entry.id is not None
    assert entry.prev_hash is None  # genesis row
    assert len(entry.row_hash) == 64
    assert entry.actor == "alice@clinic"


@pytest.mark.asyncio
async def test_hash_chain_links_entries(session: AsyncSession) -> None:
    e1 = await record_phi_access(
        session, actor="a", action=ACTION_READ, resource_type="patient_profile", resource_id="1"
    )
    e2 = await record_phi_access(
        session, actor="a", action=ACTION_WRITE, resource_type="patient_profile", resource_id="1"
    )
    e3 = await record_phi_access(
        session,
        actor="system",
        action=ACTION_EXTERNAL_LLM_CALL,
        resource_type="match_session",
        resource_id="abc",
    )
    assert e1.prev_hash is None
    assert e2.prev_hash == e1.row_hash
    assert e3.prev_hash == e2.row_hash
    assert len({e1.row_hash, e2.row_hash, e3.row_hash}) == 3


@pytest.mark.asyncio
async def test_verify_chain_ok(session: AsyncSession) -> None:
    for i in range(5):
        await record_phi_access(
            session,
            actor="alice",
            action=ACTION_READ,
            resource_type="patient_profile",
            resource_id=f"pt-{i}",
            metadata={"field_count": i},
        )
    await session.flush()
    ok, errors = await verify_chain(session)
    assert ok is True
    assert errors == []


@pytest.mark.asyncio
async def test_verify_chain_detects_tamper(session: AsyncSession) -> None:
    e1 = await record_phi_access(session, actor="a", action=ACTION_READ, resource_type="pt", resource_id="1")
    await record_phi_access(session, actor="a", action=ACTION_WRITE, resource_type="pt", resource_id="1")
    await session.flush()

    # Tamper: mutate the first row's actor in place
    e1.actor = "attacker"
    await session.flush()

    ok, errors = await verify_chain(session)
    assert ok is False
    assert any("row_hash mismatch" in e for e in errors)


@pytest.mark.asyncio
async def test_verify_chain_detects_broken_link(session: AsyncSession) -> None:
    e1 = await record_phi_access(session, actor="a", action=ACTION_READ, resource_type="pt", resource_id="1")
    e2 = await record_phi_access(session, actor="a", action=ACTION_WRITE, resource_type="pt", resource_id="1")
    await session.flush()

    # Tamper: rewrite e2's prev_hash so it no longer points at e1
    e2.prev_hash = "0" * 64
    await session.flush()

    ok, errors = await verify_chain(session)
    assert ok is False
    # Either the link mismatch or the row_hash mismatch will fire.
    assert any(f"row {e2.id}" in e for e in errors)

    # Sanity: keep e1 referenced
    assert e1.id is not None


@pytest.mark.asyncio
async def test_rejects_unknown_action(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="Unknown audit action"):
        await record_phi_access(session, actor="a", action="yolo", resource_type="pt")


@pytest.mark.asyncio
async def test_requires_actor(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="actor is required"):
        await record_phi_access(session, actor="", action=ACTION_READ, resource_type="pt")


@pytest.mark.asyncio
async def test_requires_resource_type(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="resource_type is required"):
        await record_phi_access(session, actor="a", action=ACTION_READ, resource_type="")


def test_compute_row_hash_is_deterministic() -> None:
    ts = datetime(2026, 4, 5, 12, 0, 0, tzinfo=timezone.utc)
    h1 = compute_row_hash(
        occurred_at=ts,
        actor="alice",
        action="read",
        resource_type="patient_profile",
        resource_id="42",
        purpose="match",
        metadata={"k": 1},
        prev_hash=None,
    )
    h2 = compute_row_hash(
        occurred_at=ts,
        actor="alice",
        action="read",
        resource_type="patient_profile",
        resource_id="42",
        purpose="match",
        metadata={"k": 1},
        prev_hash=None,
    )
    assert h1 == h2
    # Differing field → different hash
    h3 = compute_row_hash(
        occurred_at=ts,
        actor="bob",
        action="read",
        resource_type="patient_profile",
        resource_id="42",
        purpose="match",
        metadata={"k": 1},
        prev_hash=None,
    )
    assert h3 != h1
