"""The run workflow: the order of a run's steps. It decides; it never touches the world or a table.

Temporal replays this function from the run's history after every wait or crash, so the code must make the
same decisions from the same history: no clock, randomness, environment or network here. Everything it
needs arrives as input or comes back from an activity.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

# One write to Postgres. Longer than this means the database is gone, not slow.
RECORD_TIMEOUT = timedelta(seconds=10)
# Postgres blinks, the second try lands; an outage keeps trying every 30 s until it is back, the run waits.
RECORD_RETRY = RetryPolicy(maximum_interval=timedelta(seconds=30))

TASK_QUEUE = "workflow"


@dataclass
class RunInput:
    run_id: str
    tenant_id: str


@dataclass
class RecordInput:
    """What `record`, the one activity that writes about a run, needs for one write."""

    run_id: str
    tenant_id: str
    run_status: str
    stage: str
    stage_status: str
    text: str


@workflow.defn(name="run")
class RunWorkflow:
    def __init__(self) -> None:
        self.decision: str | None = None

    @workflow.signal
    def decide(self, decision: str) -> None:
        """The owner's answer at the review: "approve" or "discard". The API checks it before sending."""
        self.decision = decision

    @workflow.run
    async def run(self, input: RunInput) -> str:
        await self._record(input, "running", "start", "completed", "Run started")
        await self._record(input, "awaiting_review", "review", "started", "Awaiting your review")
        await workflow.wait_condition(lambda: self.decision is not None)
        status = "saved" if self.decision == "approve" else "discarded"
        await self._record(input, status, "review", "completed", status.capitalize())
        return status

    async def _record(self, input: RunInput, run_status: str, stage: str, stage_status: str, text: str) -> int:
        return await workflow.execute_activity(
            "record",
            RecordInput(input.run_id, input.tenant_id, run_status, stage, stage_status, text),
            start_to_close_timeout=RECORD_TIMEOUT,
            retry_policy=RECORD_RETRY,
        )
