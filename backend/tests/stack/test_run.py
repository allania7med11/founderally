"""One run through the real stack: compose Postgres, Temporal and the worker container (`make up`, `make migrate`).

The test plays the API's part for now: it inserts the `queued` row and starts the workflow. Commit 4 moves that
behind the routes.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import insert, select
from temporalio.client import Client

from db.engine import engine
from db.models import AWAITING_REVIEW, QUEUED, SAVED, Run, RunEvent
from settings import settings
from workflows.run import TASK_QUEUE, RunInput, RunWorkflow

# A worker pick-up plus one write takes well under a second; longer means the stack is not up.
STACK_TIMEOUT = 30

pytestmark = pytest.mark.stack


async def status_of(run_id: uuid.UUID) -> str:
    async with engine().connect() as conn:
        return await conn.scalar(select(Run.status).where(Run.run_id == run_id))


async def until_status(run_id: uuid.UUID, status: str) -> None:
    while await status_of(run_id) != status:
        await asyncio.sleep(0.2)


async def events_of(run_id: uuid.UUID) -> list[tuple[int, str, str, str]]:
    async with engine().connect() as conn:
        rows = await conn.execute(
            select(RunEvent.seq, RunEvent.stage, RunEvent.status, RunEvent.text)
            .where(RunEvent.run_id == run_id)
            .order_by(RunEvent.seq)
        )
        return [tuple(r) for r in rows]


async def test_run_pauses_at_review_and_resumes_on_decide() -> None:
    run_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    async with engine().begin() as conn:
        await conn.execute(
            insert(Run).values(
                run_id=run_id, tenant_id=tenant_id, thread_id=uuid.uuid4(), brief_id=uuid.uuid4(), status=QUEUED
            )
        )

    client = await Client.connect(settings().temporal_address, namespace=settings().temporal_namespace)
    handle = await client.start_workflow(
        RunWorkflow.run, RunInput(run_id=str(run_id), tenant_id=str(tenant_id)), id=str(run_id), task_queue=TASK_QUEUE
    )

    await asyncio.wait_for(until_status(run_id, AWAITING_REVIEW), timeout=STACK_TIMEOUT)
    assert await events_of(run_id) == [
        (1, "start", "completed", "Run started"),
        (2, "review", "started", "Awaiting your review"),
    ]

    await handle.signal(RunWorkflow.decide, "approve")
    assert await asyncio.wait_for(handle.result(), timeout=STACK_TIMEOUT) == SAVED
    assert await status_of(run_id) == SAVED
    assert (await events_of(run_id))[2] == (3, "review", "completed", "Saved")
