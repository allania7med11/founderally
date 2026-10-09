"""The worker: polls one task queue and hosts the workflow and the `record` activity. Stops on SIGTERM or SIGINT."""

import asyncio
import json
import logging
import signal
from logging.config import dictConfig

from temporalio.client import Client
from temporalio.worker import Worker

from activities.record import record
from settings import settings
from workflows.run import RunWorkflow

log = logging.getLogger("worker")


async def main() -> None:
    with open("logging.json") as f:
        dictConfig(json.load(f))
    s = settings()
    client = await Client.connect(s.temporal_address, namespace=s.temporal_namespace)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    async with Worker(client, task_queue=s.queue, workflows=[RunWorkflow], activities=[record]):
        log.info("worker started", extra={"queue": s.queue, "temporal": s.temporal_address})
        await stop.wait()
    log.info("worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
