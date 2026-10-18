"""A as a LangGraph graph: search -> extract -> verify. Every worker registers it, because the workflow walks it;
each node runs as an activity on queue `a`, so only worker-a runs the nodes."""

from datetime import timedelta

from langgraph.graph import END, START, StateGraph
from temporalio.common import RetryPolicy

from activities.research import Researcher
from workflows.run import ResearchState

QUEUE = "a"
# Three missed heartbeats (one every 10 s) fail the attempt, and a worker on the queue retries it at once.
HEARTBEAT_TIMEOUT = timedelta(seconds=30)
# A blink of Postgres or a provider: the next attempt lands. An outage: one attempt every 30 s until it is back.
NODE_RETRY = RetryPolicy(maximum_interval=timedelta(seconds=30))
# One attempt of a node. Search: Tavily's three tries of 20 s. Extract: the model asked twice, each with the
# client's three retries of 60 s. Verify: only reads and writes rows.
SEARCH_TIMEOUT = timedelta(minutes=2)
EXTRACT_TIMEOUT = timedelta(minutes=10)
VERIFY_TIMEOUT = timedelta(seconds=30)


def build_research_graph(researcher: Researcher) -> StateGraph:
    g = StateGraph(ResearchState)
    g.add_node(
        "search",
        researcher.search_node,
        metadata={
            "execute_in": "activity",
            "task_queue": QUEUE,
            "start_to_close_timeout": SEARCH_TIMEOUT,
            "heartbeat_timeout": HEARTBEAT_TIMEOUT,
            "retry_policy": NODE_RETRY,
        },
    )
    g.add_node(
        "extract",
        researcher.extract_node,
        metadata={
            "execute_in": "activity",
            "task_queue": QUEUE,
            "start_to_close_timeout": EXTRACT_TIMEOUT,
            "heartbeat_timeout": HEARTBEAT_TIMEOUT,
            "retry_policy": NODE_RETRY,
        },
    )
    g.add_node(
        "verify",
        researcher.verify_node,
        metadata={
            "execute_in": "activity",
            "task_queue": QUEUE,
            "start_to_close_timeout": VERIFY_TIMEOUT,
            "heartbeat_timeout": HEARTBEAT_TIMEOUT,
            "retry_policy": NODE_RETRY,
        },
    )
    g.add_edge(START, "search")
    g.add_edge("search", "extract")
    g.add_edge("extract", "verify")
    g.add_edge("verify", END)
    return g
