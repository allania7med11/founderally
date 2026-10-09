"""One async engine per process, built from DATABASE_URL on first use. Connections open lazily, per transaction."""

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from settings import settings


@lru_cache
def engine() -> AsyncEngine:
    return create_async_engine(settings().database_url)
