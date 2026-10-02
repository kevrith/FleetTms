from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.tenancy import current_business_id

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine | None:
    global _engine
    if _engine is None and settings.database_url:
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    engine = get_engine()
    if engine is None:
        raise RuntimeError("DATABASE_URL is not configured")
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    return _sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    """One session per request. Always starts with no tenant context; auth sets it."""
    current_business_id.set(None)
    async with get_sessionmaker()() as session:
        try:
            yield session
        finally:
            current_business_id.set(None)


async def database_is_up() -> bool:
    engine = get_engine()
    if engine is None:
        return False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - any failure means "down"
        return False
