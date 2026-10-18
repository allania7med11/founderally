"""`record` called twice with one activity id, as Temporal retries a worker that saved and died before reporting.
Needs Postgres (`make up`, `make migrate`), no Temporal."""

import uuid

import pytest
from sqlalchemy import func, select
from temporalio.testing import ActivityEnvironment

from activities.record import record
from db.engine import engine
from db.models import Run, RunEvent
from tests.research_fakes import new_run
from workflows.run import RecordInput

pytestmark = pytest.mark.stack


async def test_same_activity_id_writes_once() -> None:
    """`record` is idempotent: the same step called twice writes once. The cat café run writes "Run started"; the row
    is saved under (run_id, activity_id), unique together: every run counts its activity ids from 1, so the id alone
    repeats across runs. The worker crashes before saying "done", so Temporal runs the step again with the same id.
    The second call finds the row under that key and writes nothing: one row, seq 1."""
    run_id, tenant_id = await new_run()
    write = RecordInput(run_id, tenant_id, "running", "start", "completed", "Run started")
    # One environment, so both calls carry the same activity id, as a retry does.
    env = ActivityEnvironment()

    first = await env.run(record, write)
    second = await env.run(record, write)

    assert first == second == 1
    async with engine().connect() as conn:
        events = await conn.scalar(select(func.count()).where(RunEvent.run_id == uuid.UUID(run_id)))
        last_seq = await conn.scalar(select(Run.last_seq).where(Run.run_id == uuid.UUID(run_id)))
    assert events == 1
    assert last_seq == 1
