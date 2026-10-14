"""The run workflow: the order of a run's steps. It decides; it never touches the world or a table.

Temporal replays this function from the run's history after every wait or crash, so the code must make the
same decisions from the same history: no clock, randomness, environment or network here. Everything it
needs arrives as input or comes back from an activity.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

# Our pydantic models are deterministic; the sandbox reloads modules per run unless told to pass them through.
# `annotated_types` is a workaround: pydantic loads it inside a function, the sandbox gets its own copy and the
# field caps stop being enforced (temporalio/sdk-python issue 1897, fixed 2026-10-05, not yet released at 1.34.0).
# Remove the line when the SDK is bumped past that fix.
with workflow.unsafe.imports_passed_through():
    import annotated_types  # noqa: F401

    from contracts.brief import Brief

# One write to Postgres. Longer than this means the database is gone, not slow.
RECORD_TIMEOUT = timedelta(seconds=10)
# Postgres blinks, the second try lands; an outage keeps trying every 30 s until it is back, the run waits.
RECORD_RETRY = RetryPolicy(maximum_interval=timedelta(seconds=30))

TASK_QUEUE = "workflow"


@dataclass
class RunInput:
    run_id: str
    tenant_id: str
    # The confirmed brief, whole: the workflow hands it to the researcher; no activity reads the briefs table.
    brief: Brief


@dataclass
class ResearchInput:
    """What the researcher needs for one pass: the brief and the key its rows are saved under."""

    run_id: str
    tenant_id: str
    brief: Brief
    round: int
    pass_no: int


@dataclass
class ResearchOutput:
    """What one pass hands back: the verified rows' ids and what the pass paid. A pass read back from the row
    paid nothing in this attempt; its tokens are in LangSmith under the run id."""

    competitor_ids: list[str]
    rows_found: int
    reason: str | None
    tokens_in: int
    tokens_out: int


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
