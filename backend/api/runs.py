"""The three things the page does with a run: start one, answer its review, ask where it is."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import insert
from temporalio.service import RPCError, RPCStatusCode

from api.deps import OwnedRun, Temporal, Tenant
from db.engine import engine
from db.models import AWAITING_REVIEW, QUEUED, Run
from workflows.run import TASK_QUEUE, RunInput, RunWorkflow

router = APIRouter(prefix="/api/runs")

TEMPORAL_DOWN = "could not reach the run engine, try again"


def unavailable(error: RPCError) -> HTTPException:
    """Only a dead server is the caller's 503, retry later; any other refusal is ours to see, so it propagates."""
    if error.status == RPCStatusCode.UNAVAILABLE:
        return HTTPException(503, TEMPORAL_DOWN)
    raise error


class StartRun(BaseModel):
    thread_id: uuid.UUID
    brief_id: uuid.UUID


class Decision(BaseModel):
    decision: Literal["approve", "discard"]


class RunOut(BaseModel):
    run_id: uuid.UUID
    thread_id: uuid.UUID
    brief_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime


@router.post("", status_code=201)
async def start_run(body: StartRun, tenant: Tenant, temporal: Temporal) -> dict[str, uuid.UUID]:
    """Row first, as `queued`, then Temporal: the first `record` updates that row and fails the run if it is absent.
    Temporal down leaves the row `queued`, the state the word means (default)."""
    run_id = uuid.uuid4()
    async with engine().begin() as conn:
        await conn.execute(
            insert(Run).values(
                run_id=run_id, tenant_id=tenant, thread_id=body.thread_id, brief_id=body.brief_id, status=QUEUED
            )
        )
    try:
        await temporal.start_workflow(
            RunWorkflow.run,
            RunInput(run_id=str(run_id), tenant_id=str(tenant)),
            id=str(run_id),
            task_queue=TASK_QUEUE,
        )
    except RPCError as e:
        raise unavailable(e) from None
    return {"run_id": run_id}


@router.post("/{run_id}/decide", status_code=202)
async def decide(body: Decision, run: OwnedRun, temporal: Temporal) -> Response:
    """Checks our row, then signals. Nothing is written here, so a failure leaves the run exactly as it was."""
    if run.status != AWAITING_REVIEW:
        raise HTTPException(409, f"run is {run.status}, not {AWAITING_REVIEW}")
    try:
        await temporal.get_workflow_handle(str(run.run_id)).signal(RunWorkflow.decide, body.decision)
    except RPCError as e:
        raise unavailable(e) from None
    return Response(status_code=202)


@router.get("/{run_id}")
async def get_run(run: OwnedRun) -> RunOut:
    return RunOut.model_validate(run, from_attributes=True)
