"""
Async SQLAlchemy engine + session factory.

Supports both PostgreSQL (asyncpg driver) and SQLite (aiosqlite driver) via
the DATABASE_URL environment variable.  SQLite is the default so the service
works without any external infrastructure during development.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    # SQLite needs check_same_thread=False when used with asyncio
    _connect_args = {"check_same_thread": False}
elif settings.db_require_ssl:
    # asyncpg requires ssl passed as a connect_arg, not a URL query param
    _connect_args = {"ssl": "require"}

engine = create_async_engine(
    settings.database_url,
    echo=False,       # set True to log every SQL statement
    future=True,
    connect_args=_connect_args,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# ---------------------------------------------------------------------------
# Base for ORM models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency — yields a session and guarantees cleanup
# ---------------------------------------------------------------------------


async def get_db() -> AsyncSession:  # type: ignore[return]
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
