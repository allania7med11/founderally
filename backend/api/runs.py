"""The three things the page does with a run: start one, answer its review, ask where it is."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import insert
from temporalio.common import WorkflowIDReusePolicy
from temporalio.service import RPCError, RPCStatusCode

from api.deps import OwnedRun, Temporal, Tenant
from contracts.brief import Brief
from db.engine import engine
from db.models import AWAITING_REVIEW, CONFIRMED, QUEUED, Run
from db.models import Brief as BriefRow
from workflows.run import TASK_QUEUE, RunInput, RunWorkflow

router = APIRouter(prefix="/api/runs")

TEMPORAL_DOWN = "could not reach the run engine, try again"


def unavailable(error: RPCError) -> HTTPException:
    """Only a dead server is the caller's 503, retry later; any other refusal is ours to see, so it propagates."""
    if error.status == RPCStatusCode.UNAVAILABLE:
        return HTTPException(503, TEMPORAL_DOWN)
    raise error


class StartRun(BaseModel):
    """Start with the brief in the request: there is no conversation yet to propose it. The conversation ticket
    turns this into `{thread_id, brief_id}` pointing at a proposed row."""

    thread_id: uuid.UUID
    brief: Brief


class Decision(BaseModel):
    decision: Literal["approve", "discard"]


class RunOut(BaseModel):
    run_id: uuid.UUID
    thread_id: uuid.UUID
    status: str
    last_seq: int
    created_at: datetime
    updated_at: datetime


@router.post("", status_code=201)
async def start_run(
    body: StartRun, tenant: Tenant, temporal: Temporal
) -> dict[str, uuid.UUID]:
    """Rows first, the run as `queued` then its brief as confirmed round 1, then Temporal: the first `record` updates
    the run row and fails the run if it is absent. Temporal down leaves the row `queued`, the state the word means
    (default). The run id is the workflow id, and a second start with the same id is refused, never a second run."""
    run_id = uuid.uuid4()
    brief_id = uuid.uuid4()
    async with engine().begin() as conn:
        await conn.execute(
            insert(Run).values(
                run_id=run_id, tenant_id=tenant, thread_id=body.thread_id, status=QUEUED
            )
        )
        await conn.execute(
            insert(BriefRow).values(
                brief_id=brief_id,
                tenant_id=tenant,
                thread_id=body.thread_id,
                run_id=run_id,
                round=1,
                status=CONFIRMED,
                brief=body.brief.model_dump(),
            )
        )
    try:
        await temporal.start_workflow(
            RunWorkflow.run,
            RunInput(run_id=str(run_id), tenant_id=str(tenant), brief=body.brief),
            id=str(run_id),
            task_queue=TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
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
        await temporal.get_workflow_handle(str(run.run_id)).signal(
            RunWorkflow.decide, body.decision
        )
    except RPCError as e:
        raise unavailable(e) from None
    return Response(status_code=202)


@router.get("/{run_id}")
async def get_run(run: OwnedRun) -> RunOut:
    return RunOut.model_validate(run, from_attributes=True)
