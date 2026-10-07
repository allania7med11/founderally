"""The workflow alone, on Temporal's test server, with a fake `record`: three status writes, in order."""

import asyncio

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from workflows.run import TASK_QUEUE, RecordInput, RunInput, RunWorkflow


async def test_run_pauses_at_review_and_resumes_on_decide() -> None:
    writes: list[RecordInput] = []

    @activity.defn(name="record")
    async def fake_record(write: RecordInput) -> int:
        writes.append(write)
        return len(writes)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[RunWorkflow], activities=[fake_record]):
            handle = await env.client.start_workflow(
                RunWorkflow.run, RunInput(run_id="r1", tenant_id="t1"), id="r1", task_queue=TASK_QUEUE
            )
            while len(writes) < 2:
                await asyncio.sleep(0.05)
            assert [w.run_status for w in writes] == ["running", "awaiting_review"]

            await handle.signal(RunWorkflow.decide, "approve")
            assert await handle.result() == "saved"

    assert [w.run_status for w in writes] == ["running", "awaiting_review", "saved"]
    assert [(w.stage, w.stage_status) for w in writes] == [
        ("start", "completed"),
        ("review", "started"),
        ("review", "completed"),
    ]
