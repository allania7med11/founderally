"""The worker: polls one task queue, `workflow` or `a`, and hosts what that queue runs. Stops on SIGTERM or SIGINT.

Both register the research graph: the workflow worker walks it, worker-a runs its nodes."""

import asyncio
import json
import logging
import signal
from logging.config import dictConfig

from temporalio.client import Client
from temporalio.contrib.langgraph import LangGraphPlugin
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from activities.providers import real_researcher
from activities.record import record
from activities.research import Researcher
from activities.research_graph import QUEUE as RESEARCH_QUEUE
from activities.research_graph import build_research_graph
from settings import settings
from workflows.run import RESEARCH_GRAPH, TASK_QUEUE, RunWorkflow

log = logging.getLogger("worker")


async def runs_on_worker_a(*args, **kwargs):
    raise RuntimeError("the researcher's providers run on worker-a only")


def configure_logging() -> None:
    with open("logging.json") as f:
        dictConfig(json.load(f))


async def main() -> None:
    s = settings()
    client = await Client.connect(
        s.temporal_address, namespace=s.temporal_namespace, data_converter=pydantic_data_converter
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    if s.queue == TASK_QUEUE:
        # Walks the graph; its nodes run on queue `a`, so stand-ins, no keys.
        researcher = Researcher(search=runs_on_worker_a, extract=runs_on_worker_a)
        research = LangGraphPlugin(graphs={RESEARCH_GRAPH: build_research_graph(researcher)})
        worker = Worker(client, task_queue=s.queue, workflows=[RunWorkflow], activities=[record], plugins=[research])
    elif s.queue == RESEARCH_QUEUE:
        # Runs the nodes: the real providers, which fail at start without the keys.
        researcher = real_researcher()
        research = LangGraphPlugin(graphs={RESEARCH_GRAPH: build_research_graph(researcher)})
        worker = Worker(client, task_queue=s.queue, plugins=[research])
    else:
        raise ValueError(f"no worker set up for queue {s.queue!r}")
    async with worker:
        log.info("worker started", extra={"queue": s.queue, "temporal": s.temporal_address})
        await stop.wait()
    log.info("worker stopped")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(main())
