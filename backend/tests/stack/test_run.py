"""One run through the real stack, as the page would drive it: `make up`, `make migrate`, then this.

The steps of the ticket: start, research through a worker-a restart, reach the review, survive a workflow worker
restart, decide, decide again; then one refusal from Temporal that must not read as "down".
The API is the one under test on :8000; the workers are the compose containers. Research is real: worker-a calls
Tavily and OpenAI, so the test needs both keys in `.env` and skips without them.
"""

import asyncio
import os
import re
import uuid
from pathlib import Path

import pytest
from db.engine import engine
from db.models import (
    AWAITING_REVIEW,
    CONFIRMED,
    QUEUED,
    RUNNING,
    SAVED,
    Brief,
    Competitor,
    RunEvent,
)
from httpx import AsyncClient, Limits
from settings import settings
from sqlalchemy import select
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.contrib.pydantic import pydantic_data_converter
from tests.cat_cafe import BRIEF

# A worker pick-up plus one write takes well under a second; a worker restart a few seconds. Longer means the
# stack is not up.
STACK_TIMEOUT = 10
# Real research: two searches, one model call, maybe a second pass. Longer means a provider is stuck.
RESEARCH_TIMEOUT = 180
REPO = Path(__file__).resolve().parents[3]

pytestmark = [
    pytest.mark.stack,
    pytest.mark.skipif(
        not (os.environ.get("TAVILY_API_KEY") and os.environ.get("OPENAI_API_KEY")),
        reason="research is part of every run: put TAVILY_API_KEY and OPENAI_API_KEY in .env",
    ),
]


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
    temporal = await Client.connect(
        settings().temporal_address, namespace=settings().temporal_namespace, data_converter=pydantic_data_converter
    )
    thread_id = uuid.uuid4()
    start = {"thread_id": str(thread_id), "brief": BRIEF.model_dump()}

    async def status_is(run_id: uuid.UUID, status: str) -> bool:
        return (await api.get(f"/api/runs/{run_id}")).json()["status"] == status

    async def has_step(run_id: uuid.UUID, stage: str, status: str) -> bool:
        return any(e[1:3] == (stage, status) for e in await events_of(run_id))

    async def temporal_status(run_id: uuid.UUID) -> WorkflowExecutionStatus:
        return (await temporal.get_workflow_handle(str(run_id)).describe()).status

    # 1. Start: the row exists at once, then the first step lands; the test waits for that event.
    started = await api.post("/api/runs", json=start)
    assert started.status_code == 201
    run_id = uuid.UUID(started.json()["run_id"])
    run = (await api.get(f"/api/runs/{run_id}")).json()
    assert run["status"] in (QUEUED, RUNNING, AWAITING_REVIEW)
    # The brief is a row of its own, confirmed, round 1, pointing at its run.
    async with engine().connect() as conn:
        brief = (await conn.execute(select(Brief).where(Brief.run_id == run_id))).one()
    assert (brief.status, brief.round, brief.brief) == (CONFIRMED, 1, BRIEF.model_dump())
    await asyncio.wait_for(until(has_step, run_id, "start", "completed"), timeout=STACK_TIMEOUT)
    assert (await events_of(run_id))[0] == (1, "start", "completed", "Run started")
    assert (await api.get(f"/api/runs/{run_id}")).json()["status"] in (RUNNING, AWAITING_REVIEW)

    # 2. Research: worker-a searches, extracts and verifies, then the run says how many competitors it kept.
    # Worker-a restarts once research has started: the node it was running is retried, and the run still finishes.
    await asyncio.wait_for(until(has_step, run_id, "research", "started"), timeout=STACK_TIMEOUT)
    restart_a = await asyncio.create_subprocess_exec("docker", "compose", "restart", "worker-a", cwd=REPO)
    assert await restart_a.wait() == 0
    await asyncio.wait_for(until(has_step, run_id, "research", "completed"), timeout=RESEARCH_TIMEOUT)
    events = await events_of(run_id)
    assert events[1] == (2, "research", "started", "Researching")
    assert events[2][:3] == (3, "research", "completed")
    verified = re.fullmatch(r"(\d+) competitors verified", events[2][3])
    assert verified is not None
    # Cat cafés in Tunis exist: zero means search, extract or verify is broken, not that the market is empty.
    assert int(verified[1]) >= 1
    # For the pull request: the final result, the rows of the last pass.
    async with engine().connect() as conn:
        query = select(Competitor.pass_no, Competitor.name, Competitor.source_url).where(Competitor.run_id == run_id)
        rows = (await conn.execute(query)).all()
    last_pass = max(pass_no for pass_no, _, _ in rows)
    for pass_no, name, source_url in rows:
        if pass_no == last_pass:
            print(f"verified: {name}  {source_url}")

    # 3. The review: the run stops and says so.
    await asyncio.wait_for(until(status_is, run_id, AWAITING_REVIEW), timeout=STACK_TIMEOUT)
    assert (await events_of(run_id))[3] == (4, "review", "started", "Awaiting your review")

    # 4. The world moves on: the workflow worker restarts, the run is untouched and still open.
    restart = await asyncio.create_subprocess_exec("docker", "compose", "restart", "worker", cwd=REPO)
    assert await restart.wait() == 0
    assert await status_is(run_id, AWAITING_REVIEW)
    assert await temporal_status(run_id) == WorkflowExecutionStatus.RUNNING

    # Another tenant cannot decide it: 404, as if the run did not exist, and the run still waits for its owner.
    stranger = {"X-Tenant-Id": str(uuid.uuid4())}
    refused = await api.post(f"/api/runs/{run_id}/decide", json={"decision": "discard"}, headers=stranger)
    assert refused.status_code == 404
    assert await status_is(run_id, AWAITING_REVIEW)

    # 5. Decide: accepted now, saved shortly after, closed in Temporal.
    assert (await api.post(f"/api/runs/{run_id}/decide", json={"decision": "approve"})).status_code == 202
    await asyncio.wait_for(until(status_is, run_id, SAVED), timeout=STACK_TIMEOUT)
    assert (await events_of(run_id))[4] == (5, "review", "completed", "Saved")
    assert await temporal_status(run_id) == WorkflowExecutionStatus.COMPLETED

    # 6. Decide again: refused, nothing changes.
    before = (await api.get(f"/api/runs/{run_id}")).json()
    # `last_seq` is the GET's cursor for the page: five events saved, so five.
    assert before["last_seq"] == 5
    assert (await api.post(f"/api/runs/{run_id}/decide", json={"decision": "discard"})).status_code == 409
    assert (await api.get(f"/api/runs/{run_id}")).json() == before
    assert len(await events_of(run_id)) == 5

    # Another tenant sees nothing of it.
    other = await api.get(f"/api/runs/{run_id}", headers={"X-Tenant-Id": str(uuid.uuid4())})
    assert other.status_code == 404

    # 7. A refusal that is not "Temporal down" is not hidden behind a 503. A second run is terminated behind the
    # API's back, as an operator would in the Temporal UI: the workflow is closed, no `record` ran, so our row still
    # says awaiting_review and the 409 check passes; Temporal then refuses the signal (its message says "already
    # completed" for any closed run) and the API lets it surface as a 500.
    started = await api.post("/api/runs", json=start | {"thread_id": str(uuid.uuid4())})
    killed = uuid.UUID(started.json()["run_id"])
    await asyncio.wait_for(until(status_is, killed, AWAITING_REVIEW), timeout=RESEARCH_TIMEOUT)
    await temporal.get_workflow_handle(str(killed)).terminate("killed by the test")
    assert (await api.post(f"/api/runs/{killed}/decide", json={"decision": "approve"})).status_code == 500
    assert await status_is(killed, AWAITING_REVIEW)
    await api.aclose()
