"""`heartbeating()`: beats for the whole block, so a long call still tells the server the worker is alive and a
cancel can reach it. The stop is in the `finally`, so no activity can forget it."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from temporalio import activity

# Three missed beats fail the attempt.
HEARTBEAT_EVERY = 10


async def _beat() -> None:
    while True:
        activity.heartbeat()
        await asyncio.sleep(HEARTBEAT_EVERY)


@asynccontextmanager
async def heartbeating() -> AsyncGenerator[None]:
    beat = asyncio.create_task(_beat())
    try:
        yield
    finally:
        beat.cancel()
