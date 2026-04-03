"""Nightly trial refresh — pre-warms the DB cache for focus cancer types.

Queries ClinicalTrials.gov for each cancer type and stores results
in TrialCacheDB so searches during the day hit the DB instead of
the live API.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db_models import TrialCacheDB
from logging_config import get_logger
from trials_client import search_nci_trials, search_trials

logger = get_logger("kyriaki.trial_refresh")

# Focus cancer types to pre-warm (from CLAUDE.md)
FOCUS_CANCER_TYPES = [
    "Non-Small Cell Lung Cancer",
    "Small Cell Lung Cancer",
    "Triple Negative Breast Cancer",
    "HER2+ Breast Cancer",
    "Hormone Receptor+ Breast Cancer",
    "Colorectal Cancer",
    "Pancreatic Cancer",
    "Melanoma",
    "Bladder Cancer",
    "Ovarian Cancer",
    "Prostate Cancer",
    "Acute Lymphoblastic Leukemia",
    "Neuroblastoma",
    "Osteosarcoma",
    "Ewing Sarcoma",
    "Glioblastoma",
]

# Page sizes to pre-warm (common request sizes)
REFRESH_PAGE_SIZES = [10, 20, 50]


def _make_cache_key(cancer_type: str, page_size: int, source: str = "ctgov") -> str:
    """Build a cache key matching the trials_client format."""
    if source == "nci":
        return f"NCI:{cancer_type}|None|None|{page_size}|None|None"
    return f"{cancer_type}|None|None|{page_size}|None|None"


async def refresh_cancer_type(
    session: AsyncSession,
    cancer_type: str,
    page_size: int = 50,
    ttl_hours: int = 24,
) -> int:
    """Refresh cache for a single cancer type. Returns trial count."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=ttl_hours)

    # Fetch from ClinicalTrials.gov
    try:
        trials = await search_trials(cancer_type, page_size=page_size)
    except Exception as e:
        logger.error("refresh.fetch_failed", cancer_type=cancer_type, error=str(e))
        return 0

    cache_key = _make_cache_key(cancer_type, page_size)

    # Upsert into DB
    stmt = select(TrialCacheDB).where(TrialCacheDB.cache_key == cache_key)
    result = await session.execute(stmt)
    existing = result.scalars().first()

    if existing:
        existing.trials_json = trials
        existing.trial_count = len(trials)
        existing.fetched_at = now
        existing.expires_at = expires
    else:
        session.add(
            TrialCacheDB(
                cache_key=cache_key,
                trials_json=trials,
                trial_count=len(trials),
                fetched_at=now,
                expires_at=expires,
            )
        )

    await session.flush()
    return len(trials)


async def refresh_all(session: AsyncSession) -> dict:
    """Refresh cache for all focus cancer types. Returns summary stats."""
    settings = get_settings()
    ttl = settings.trial_cache_ttl_hours
    total_trials = 0
    total_queries = 0
    errors = 0

    logger.info("refresh.start", cancer_types=len(FOCUS_CANCER_TYPES))

    for cancer_type in FOCUS_CANCER_TYPES:
        for page_size in REFRESH_PAGE_SIZES:
            try:
                count = await refresh_cancer_type(session, cancer_type, page_size, ttl)
                total_trials += count
                total_queries += 1
                logger.info(
                    "refresh.cached",
                    cancer_type=cancer_type,
                    page_size=page_size,
                    trials=count,
                )
                # Rate limit: ClinicalTrials.gov allows 10 req/sec
                await asyncio.sleep(0.15)
            except Exception as e:
                errors += 1
                logger.error("refresh.error", cancer_type=cancer_type, error=str(e))

        # Also refresh NCI-specific search
        try:
            nci_trials = await search_nci_trials(cancer_type, page_size=50)
            nci_key = _make_cache_key(cancer_type, 50, source="nci")
            now = datetime.now(timezone.utc)

            stmt = select(TrialCacheDB).where(TrialCacheDB.cache_key == nci_key)
            result = await session.execute(stmt)
            existing = result.scalars().first()

            if existing:
                existing.trials_json = nci_trials
                existing.trial_count = len(nci_trials)
                existing.fetched_at = now
                existing.expires_at = now + timedelta(hours=ttl)
            else:
                session.add(
                    TrialCacheDB(
                        cache_key=nci_key,
                        trials_json=nci_trials,
                        trial_count=len(nci_trials),
                        fetched_at=now,
                        expires_at=now + timedelta(hours=ttl),
                    )
                )
            await session.flush()
            total_queries += 1
            await asyncio.sleep(0.15)
        except Exception as e:
            errors += 1
            logger.warning("refresh.nci_error", cancer_type=cancer_type, error=str(e))

    # Clean expired entries
    expired_count = await purge_expired(session)

    summary = {
        "cancer_types": len(FOCUS_CANCER_TYPES),
        "total_queries": total_queries,
        "total_trials_cached": total_trials,
        "errors": errors,
        "expired_purged": expired_count,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("refresh.complete", **summary)
    return summary


async def get_cached_trials(session: AsyncSession, cache_key: str) -> list[dict] | None:
    """Look up trials from the DB cache. Returns None if not found or expired."""
    now = datetime.now(timezone.utc)
    stmt = select(TrialCacheDB).where(
        TrialCacheDB.cache_key == cache_key,
        TrialCacheDB.expires_at > now,
    )
    result = await session.execute(stmt)
    entry = result.scalars().first()
    if entry:
        logger.debug("refresh.db_cache_hit", key=cache_key, trials=entry.trial_count)
        return entry.trials_json
    return None


async def purge_expired(session: AsyncSession) -> int:
    """Delete expired cache entries. Returns count deleted."""
    now = datetime.now(timezone.utc)
    stmt = delete(TrialCacheDB).where(TrialCacheDB.expires_at <= now)
    result = await session.execute(stmt)
    count = result.rowcount
    if count:
        logger.info("refresh.purged_expired", count=count)
    return count


async def get_cache_stats(session: AsyncSession) -> dict:
    """Return cache statistics."""
    now = datetime.now(timezone.utc)
    total_stmt = select(TrialCacheDB)
    total_result = await session.execute(total_stmt)
    all_entries = list(total_result.scalars().all())

    def _is_active(entry: TrialCacheDB) -> bool:
        exp = entry.expires_at
        if exp is None:
            return False
        # Handle naive datetimes from SQLite
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp > now

    active = [e for e in all_entries if _is_active(e)]
    expired = [e for e in all_entries if not _is_active(e)]

    return {
        "total_entries": len(all_entries),
        "active_entries": len(active),
        "expired_entries": len(expired),
        "total_trials_cached": sum(e.trial_count for e in active),
        "oldest_entry": min((e.fetched_at.isoformat() for e in active), default=None),
        "newest_entry": max((e.fetched_at.isoformat() for e in active), default=None),
    }
