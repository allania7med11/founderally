"""One run through the real stack, as the page would drive it: `make up`, `make migrate`, then this.

The five steps of the ticket: start, reach the review, survive a worker restart, decide, decide again;
then one refusal from Temporal that must not read as "down".
The API is the one under test on :8000; the worker is the compose container, restarted mid-wait.
"""

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient, Limits
from sqlalchemy import select
from temporalio.client import Client, WorkflowExecutionStatus

from db.engine import engine
from db.models import AWAITING_REVIEW, QUEUED, RUNNING, SAVED, RunEvent
from settings import settings

# A worker pick-up plus one write takes well under a second; a worker restart a few seconds. Longer means the
# stack is not up.
STACK_TIMEOUT = 10
REPO = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.stack


async def events_of(run_id: uuid.UUID) -> list[tuple[int, str, str, str]]:
    async with engine().connect() as conn:
        rows = await conn.execute(
            select(RunEvent.seq, RunEvent.stage, RunEvent.status, RunEvent.text)
            .where(RunEvent.run_id == run_id)
            .order_by(RunEvent.seq)
        )
        return [tuple(r) for r in rows]


async def until(check, *args):
    """Poll `check` every 0.2 s until it returns true; `wait_for` around the call sets the deadline."""
    while not await check(*args):
        await asyncio.sleep(0.2)


async def test_run_pauses_at_review_survives_a_restart_and_resumes_on_decide() -> None:
    tenant_id = uuid.uuid4()
    # No keep-alive: after a 500 the server drops the connection, and a pooled one would fail the next call.
    api = AsyncClient(
        base_url=os.environ["API_URL"],
        headers={"X-Tenant-Id": str(tenant_id)},
        limits=Limits(max_keepalive_connections=0),
    )
    temporal = await Client.connect(settings().temporal_address, namespace=settings().temporal_namespace)

    async def status_is(run_id: uuid.UUID, status: str) -> bool:
        return (await api.get(f"/api/runs/{run_id}")).json()["status"] == status

    async def has_events(run_id: uuid.UUID, n: int) -> bool:
        return len(await events_of(run_id)) >= n

    async def temporal_status(run_id: uuid.UUID) -> WorkflowExecutionStatus:
        return (await temporal.get_workflow_handle(str(run_id)).describe()).status

    # 1. Start: the row exists at once, then the first step lands. `running` lasts milliseconds here, with no
    # work in the step, so the first event is what the test waits for, not that status.
    started = await api.post("/api/runs", json={"thread_id": str(uuid.uuid4()), "brief_id": str(uuid.uuid4())})
    assert started.status_code == 201
    run_id = uuid.UUID(started.json()["run_id"])
    assert (await api.get(f"/api/runs/{run_id}")).json()["status"] in (QUEUED, RUNNING, AWAITING_REVIEW)
    await asyncio.wait_for(until(has_events, run_id, 1), timeout=STACK_TIMEOUT)
    assert (await events_of(run_id))[0] == (1, "start", "completed", "Run started")
    assert (await api.get(f"/api/runs/{run_id}")).json()["status"] in (RUNNING, AWAITING_REVIEW)

    # 2. The review: the run stops and says so.
    await asyncio.wait_for(until(status_is, run_id, AWAITING_REVIEW), timeout=STACK_TIMEOUT)
    assert (await events_of(run_id))[1] == (2, "review", "started", "Awaiting your review")

    # 3. The world moves on: the worker restarts, the run is untouched and still open.
    restart = await asyncio.create_subprocess_exec("docker", "compose", "restart", "worker", cwd=REPO)
    assert await restart.wait() == 0
    assert await status_is(run_id, AWAITING_REVIEW)
    assert await temporal_status(run_id) == WorkflowExecutionStatus.RUNNING

    # 4. Decide: accepted now, saved shortly after, closed in Temporal.
    assert (await api.post(f"/api/runs/{run_id}/decide", json={"decision": "approve"})).status_code == 202
    await asyncio.wait_for(until(status_is, run_id, SAVED), timeout=STACK_TIMEOUT)
    assert (await events_of(run_id))[2] == (3, "review", "completed", "Saved")
    assert await temporal_status(run_id) == WorkflowExecutionStatus.COMPLETED

    # 5. Decide again: refused, nothing changes.
    before = (await api.get(f"/api/runs/{run_id}")).json()
    assert (await api.post(f"/api/runs/{run_id}/decide", json={"decision": "discard"})).status_code == 409
    assert (await api.get(f"/api/runs/{run_id}")).json() == before
    assert len(await events_of(run_id)) == 3

    # Another tenant sees nothing of it.
    other = await api.get(f"/api/runs/{run_id}", headers={"X-Tenant-Id": str(uuid.uuid4())})
    assert other.status_code == 404

    # 6. A refusal that is not "Temporal down" is not hidden behind a 503. A second run is terminated behind the
    # API's back, as an operator would in the Temporal UI: the workflow is closed, no `record` ran, so our row still
    # says awaiting_review and the 409 check passes; Temporal then refuses the signal (its message says "already
    # completed" for any closed run) and the API lets it surface as a 500.
    started = await api.post("/api/runs", json={"thread_id": str(uuid.uuid4()), "brief_id": str(uuid.uuid4())})
    killed = uuid.UUID(started.json()["run_id"])
    await asyncio.wait_for(until(status_is, killed, AWAITING_REVIEW), timeout=STACK_TIMEOUT)
    await temporal.get_workflow_handle(str(killed)).terminate("killed by the test")
    assert (await api.post(f"/api/runs/{killed}/decide", json={"decision": "approve"})).status_code == 500
    assert await status_is(killed, AWAITING_REVIEW)
    await api.aclose()
