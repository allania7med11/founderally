"""One async engine per process, built from DATABASE_URL on first use. Connections open lazily, per transaction."""

from functools import lru_cache

from settings import settings
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# A session that opened a transaction and went quiet holds its locks, the run row among them, so every later write of
# that run waits. Postgres closes such a session after 10 s, the time one `record` is given.
IDLE_IN_TRANSACTION = "-c idle_in_transaction_session_timeout=10000"


@lru_cache
def engine() -> AsyncEngine:
    return create_async_engine(settings().database_url, connect_args={"options": IDLE_IN_TRANSACTION})
