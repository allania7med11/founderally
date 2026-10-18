"""The workflow alone, on Temporal's test server, with a fake `record` and a one-node fake research graph: the
status writes, in order, the pause at review, and the second pass when the first keeps too few rows."""

import asyncio
from datetime import timedelta

import pytest
from langgraph.graph import END, START, StateGraph
from temporalio import activity
from temporalio.contrib.langgraph import LangGraphPlugin
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from tests.cat_cafe import BRIEF
from workflows.run import (
    RESEARCH_GRAPH,
    TASK_QUEUE,
    RecordInput,
    ResearchState,
    RunInput,
    RunWorkflow,
    research_text,
)


async def three_rows(state: ResearchState) -> dict:
    """Three competitors kept on the first pass, so the workflow asks for no second pass."""
    return {"competitor_ids": ["c1", "c2", "c3"], "rows_found": 3, "reason": None}


async def one_then_four_rows(state: ResearchState) -> dict:
    """One competitor on pass 1, under the three the workflow wants; four on pass 2."""
    rows_found = 1 if state["pass_no"] == 1 else 4
    return {"competitor_ids": [], "rows_found": rows_found, "reason": None}


# The plugin finds a node by its module and name, so the fakes are module-level functions, never closures.
def fake_research_graph(node) -> StateGraph:
    g = StateGraph(ResearchState)
    g.add_node(
        "research",
        node,
        metadata={"execute_in": "activity", "start_to_close_timeout": timedelta(seconds=10)},
    )
    g.add_edge(START, "research")
    g.add_edge("research", END)
    return g


async def test_run_pauses_at_review_and_resumes_on_decide() -> None:
    writes: list[RecordInput] = []
    at_review = asyncio.Event()

    @activity.defn(name="record")
    async def fake_record(write: RecordInput) -> int:
        writes.append(write)
        if len(writes) == 4:
            at_review.set()
        return len(writes)

    research_graph = fake_research_graph(three_rows)
    research = LangGraphPlugin(graphs={RESEARCH_GRAPH: research_graph})
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:  # noqa: SIM117
        async with Worker(
            env.client, task_queue=TASK_QUEUE, workflows=[RunWorkflow], activities=[fake_record], plugins=[research]
        ):
            handle = await env.client.start_workflow(
                RunWorkflow.run, RunInput(run_id="r1", tenant_id="t1", brief=BRIEF), id="r1", task_queue=TASK_QUEUE
            )
            await at_review.wait()
            assert [w.run_status for w in writes] == ["running", "running", "running", "awaiting_review"]

            await handle.signal(RunWorkflow.decide, "approve")
            assert await handle.result() == "saved"

    assert [(w.stage, w.stage_status) for w in writes] == [
        ("start", "completed"),
        ("research", "started"),
        ("research", "completed"),
        ("review", "started"),
        ("review", "completed"),
    ]
    assert writes[2].text == "3 competitors verified"
    assert writes[4].run_status == "saved"


async def test_too_few_rows_runs_a_second_pass() -> None:
    """Pass 1 keeps one competitor, under the three the workflow wants, so it runs pass 2, which keeps four. The run
    reports four: only pass 2 returns that number, so the text proves pass 2 ran."""
    writes: list[RecordInput] = []
    at_review = asyncio.Event()

    @activity.defn(name="record")
    async def fake_record(write: RecordInput) -> int:
        writes.append(write)
        if len(writes) == 4:
            at_review.set()
        return len(writes)

    research_graph = fake_research_graph(one_then_four_rows)
    research = LangGraphPlugin(graphs={RESEARCH_GRAPH: research_graph})
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:  # noqa: SIM117
        async with Worker(
            env.client, task_queue=TASK_QUEUE, workflows=[RunWorkflow], activities=[fake_record], plugins=[research]
        ):
            handle = await env.client.start_workflow(
                RunWorkflow.run, RunInput(run_id="r2", tenant_id="t1", brief=BRIEF), id="r2", task_queue=TASK_QUEUE
            )
            await at_review.wait()
            # Close the run, so the worker does not stop under a workflow still waiting at review.
            await handle.signal(RunWorkflow.decide, "discard")
            await handle.result()

    assert writes[2].text == "4 competitors verified"


async def test_first_valid_decision_wins() -> None:
    """A typo, then "approve", then "discard": the typo is ignored and "approve" stands, so the run is saved."""
    writes: list[RecordInput] = []
    at_review = asyncio.Event()

    @activity.defn(name="record")
    async def fake_record(write: RecordInput) -> int:
        writes.append(write)
        if len(writes) == 4:
            at_review.set()
        return len(writes)

    research_graph = fake_research_graph(three_rows)
    research = LangGraphPlugin(graphs={RESEARCH_GRAPH: research_graph})
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:  # noqa: SIM117
        async with Worker(
            env.client, task_queue=TASK_QUEUE, workflows=[RunWorkflow], activities=[fake_record], plugins=[research]
        ):
            handle = await env.client.start_workflow(
                RunWorkflow.run, RunInput(run_id="r3", tenant_id="t1", brief=BRIEF), id="r3", task_queue=TASK_QUEUE
            )
            await at_review.wait()
            await handle.signal(RunWorkflow.decide, "aprove")
            await handle.signal(RunWorkflow.decide, "approve")
            await handle.signal(RunWorkflow.decide, "discard")
            assert await handle.result() == "saved"

    assert writes[4].run_status == "saved"


@pytest.mark.parametrize(
    ("rows_found", "reason", "text"),
    [
        (3, None, "3 competitors verified"),
        (2, None, "only 2 sourced competitors found"),
        (0, "search_unavailable", "only 0 sourced competitors found: the web search was unavailable"),
        (0, "model_answer_invalid", "only 0 sourced competitors found: the model's answer was invalid twice"),
    ],
)
def test_research_line(rows_found, reason, text) -> None:
    """Three rows or more: the count. Under three, after the second pass: the warning, and why when there was
    nothing to check."""
    found = ResearchState(
        run_id="r", tenant_id="t", brief=BRIEF, round=1, pass_no=2, rows_found=rows_found, reason=reason
    )
    assert research_text(found) == text
