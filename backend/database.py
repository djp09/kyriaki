"""Async PostgreSQL database engine and session management."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import get_settings


class Base(DeclarativeBase):
    pass


def _set_sqlite_wal(dbapi_conn, connection_record):
    """Enable WAL mode on SQLite connections for concurrent read/write access.

    Without WAL, SQLite uses file-level locking that blocks background agent
    tasks from writing while the HTTP request session is active.
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def _build_engine():
    settings = get_settings()
    is_sqlite = settings.database_url.startswith("sqlite")
    kwargs = {}
    if is_sqlite:
        kwargs.update(connect_args={"check_same_thread": False})
    else:
        kwargs.update(pool_size=10, max_overflow=20, pool_timeout=30, pool_recycle=1800)
    engine = create_async_engine(
        settings.database_url,
        echo=settings.environment == "development" and settings.log_level == "DEBUG",
        **kwargs,
    )
    if is_sqlite:
        from sqlalchemy import event

        event.listen(engine.sync_engine, "connect", _set_sqlite_wal)
    return engine


engine = _build_engine()
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI dependency — yields an async database session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_db_health() -> bool:
    """Run a lightweight query to verify database connectivity."""
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
