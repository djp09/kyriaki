"""Tests for nightly trial cache refresh."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from db_models import TrialCacheDB
from trial_refresh import (
    FOCUS_CANCER_TYPES,
    _make_cache_key,
    get_cache_stats,
    get_cached_trials,
    purge_expired,
    refresh_cancer_type,
)

_is_postgres = "postgresql" in os.environ.get("KYRIAKI_DATABASE_URL", "")


class TestCacheKey:
    def test_basic_key(self):
        key = _make_cache_key("NSCLC", 10)
        assert "NSCLC" in key
        assert "10" in key

    def test_nci_key(self):
        key = _make_cache_key("NSCLC", 50, source="nci")
        assert key.startswith("NCI:")

    def test_focus_cancer_types_not_empty(self):
        assert len(FOCUS_CANCER_TYPES) >= 10


@pytest.mark.skipif(_is_postgres, reason="Uses SQLite test DB")
class TestTrialCacheDB:
    @pytest_asyncio.fixture
    async def db_session(self):
        from database import async_session, engine
        from db_models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with async_session() as session:
            yield session

    @pytest.mark.asyncio
    async def test_refresh_cancer_type(self, db_session):
        mock_trials = [
            {"nct_id": "NCT001", "brief_title": "Trial A"},
            {"nct_id": "NCT002", "brief_title": "Trial B"},
        ]
        with patch("trial_refresh.search_trials", AsyncMock(return_value=mock_trials)):
            count = await refresh_cancer_type(db_session, "NSCLC", page_size=10, ttl_hours=24)

        assert count == 2

        # Verify stored in DB
        cached = await get_cached_trials(db_session, _make_cache_key("NSCLC", 10))
        assert cached is not None
        assert len(cached) == 2

    @pytest.mark.asyncio
    async def test_refresh_updates_existing(self, db_session):
        mock_trials_v1 = [{"nct_id": "NCT001"}]
        mock_trials_v2 = [{"nct_id": "NCT001"}, {"nct_id": "NCT002"}, {"nct_id": "NCT003"}]

        with patch("trial_refresh.search_trials", AsyncMock(return_value=mock_trials_v1)):
            await refresh_cancer_type(db_session, "NSCLC", page_size=10)

        with patch("trial_refresh.search_trials", AsyncMock(return_value=mock_trials_v2)):
            count = await refresh_cancer_type(db_session, "NSCLC", page_size=10)

        assert count == 3
        cached = await get_cached_trials(db_session, _make_cache_key("NSCLC", 10))
        assert len(cached) == 3

    @pytest.mark.asyncio
    async def test_get_cached_expired(self, db_session):
        # Insert an expired entry
        key = "expired_test"
        entry = TrialCacheDB(
            cache_key=key,
            trials_json=[{"nct_id": "NCT999"}],
            trial_count=1,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db_session.add(entry)
        await db_session.flush()

        # Should not return expired entry
        result = await get_cached_trials(db_session, key)
        assert result is None

    @pytest.mark.asyncio
    async def test_purge_expired(self, db_session):
        # Insert one active, one expired
        now = datetime.now(timezone.utc)
        db_session.add(
            TrialCacheDB(
                cache_key="active",
                trials_json=[],
                trial_count=0,
                expires_at=now + timedelta(hours=24),
            )
        )
        db_session.add(
            TrialCacheDB(
                cache_key="expired",
                trials_json=[],
                trial_count=0,
                expires_at=now - timedelta(hours=1),
            )
        )
        await db_session.flush()

        count = await purge_expired(db_session)
        assert count >= 1

        # Active entry still exists
        active = await get_cached_trials(db_session, "active")
        assert active is not None

    @pytest.mark.asyncio
    async def test_cache_stats(self, db_session):
        now = datetime.now(timezone.utc)
        db_session.add(
            TrialCacheDB(
                cache_key="stat_test",
                trials_json=[{"nct_id": "NCT001"}],
                trial_count=1,
                expires_at=now + timedelta(hours=24),
            )
        )
        await db_session.flush()

        stats = await get_cache_stats(db_session)
        assert stats["active_entries"] >= 1
        assert stats["total_trials_cached"] >= 1

    @pytest.mark.asyncio
    async def test_refresh_api_failure_returns_zero(self, db_session):
        with patch("trial_refresh.search_trials", AsyncMock(side_effect=RuntimeError("API down"))):
            count = await refresh_cancer_type(db_session, "NSCLC", page_size=10)

        assert count == 0


@pytest.mark.skipif(_is_postgres, reason="Uses SQLite test DB")
class TestRefreshEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from main import app

        with TestClient(app) as c:
            yield c

    def test_cache_stats_endpoint(self, client):
        resp = client.get("/api/admin/trial-cache/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_entries" in data
        assert "active_entries" in data
