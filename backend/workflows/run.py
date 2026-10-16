"""The run workflow: the order of a run's steps. It decides; it never touches the world or a table.

Temporal replays this function from the run's history after every wait or crash, so the code must make the
same decisions from the same history: no clock, randomness, environment or network here. Everything it
needs arrives as input or comes back from an activity.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import NotRequired, TypedDict

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.contrib.langgraph import graph

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
# The name the research graph is registered under on every worker; the workflow asks for it by name.
RESEARCH_GRAPH = "research"
# Fewer kept rows than this after pass 1: one wider pass.
MIN_ROWS = 3


@dataclass
class RunInput:
    run_id: str
    tenant_id: str
    # The confirmed brief, whole: the workflow hands it to the researcher; no activity reads the briefs table.
    brief: Brief


class ResearchState(TypedDict):
    """The research graph's state for one pass: its key and brief go in, what the pass found comes out. It crosses
    each activity boundary as JSON, so a node receives the brief as a dict and validates it."""

    run_id: str
    tenant_id: str
    brief: Brief
    round: int
    pass_no: int
    tokens_in: NotRequired[int]
    tokens_out: NotRequired[int]
    competitor_ids: NotRequired[list[str]]
    rows_found: NotRequired[int]
    reason: NotRequired[str | None]


@dataclass
class RecordInput:
    """What `record`, the one activity that writes about a run, needs for one write."""

    run_id: str
    tenant_id: str
    run_status: str
    stage: str
    stage_status: str
    text: str


# Why a pass had nothing to check, as the page says it.
REASON_TEXT = {
    "search_unavailable": "the web search was unavailable",
    "model_answer_invalid": "the model's answer was invalid twice",
}


def research_text(found: ResearchState) -> str:
    """The page's research line: the count when there are enough rows; a visible warning under three; and why, when
    a pass had nothing to check."""
    rows = found["rows_found"]
    if rows >= MIN_ROWS:
        return f"{rows} competitors verified"
    text = f"only {rows} sourced competitors found"
    reason = found.get("reason")
    if reason:
        text += f": {REASON_TEXT.get(reason, reason)}"
    return text


@workflow.defn(name="run")
class RunWorkflow:
    def __init__(self) -> None:
        self.decision: str | None = None

    @workflow.signal
    def decide(self, decision: str) -> None:
        """The owner's answer at the review: "approve" or "discard". The first valid answer stands: a second tab
        cannot flip it, and a typo sent from outside the API is ignored."""
        if self.decision is None and decision in ("approve", "discard"):
            self.decision = decision

    @workflow.run
    async def run(self, input: RunInput) -> str:
        await self._record(input, "running", "start", "completed", "Run started")

        # A: the research graph, search -> extract -> verify; each node is an activity that worker-a runs.
        research = graph(RESEARCH_GRAPH).compile()
        await self._record(input, "running", "research", "started", "Researching")
        first_pass = ResearchState(
            run_id=input.run_id, tenant_id=input.tenant_id, brief=input.brief, round=1, pass_no=1
        )
        found = await research.ainvoke(first_pass)
        if found["rows_found"] < MIN_ROWS:
            second_pass = ResearchState(
                run_id=input.run_id, tenant_id=input.tenant_id, brief=input.brief, round=1, pass_no=2
            )
            found = await research.ainvoke(second_pass)
        await self._record(input, "running", "research", "completed", research_text(found))

        await self._record(input, "awaiting_review", "review", "started", "Awaiting your review")
        await workflow.wait_condition(lambda: self.decision is not None)
        status = "saved" if self.decision == "approve" else "discarded"
        await self._record(input, status, "review", "completed", status.capitalize())
        return status

    async def _record(self, input: RunInput, run_status: str, stage: str, stage_status: str, text: str) -> int:
        record = RecordInput(input.run_id, input.tenant_id, run_status, stage, stage_status, text)
        return await workflow.execute_activity(
            "record",
            record,
            start_to_close_timeout=RECORD_TIMEOUT,
            retry_policy=RECORD_RETRY,
        )
