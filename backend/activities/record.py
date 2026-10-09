"""`record`, the one activity that writes about a run. The workflow decides where the run is; this writes it.

One call, one transaction, three writes: the run's new status, one event line with the next seq, and a NOTIFY
so the API can push the line to the page. Temporal may retry or replay a step after a crash; one writer with one
transaction means a repeated call writes once and whole, never twice or half.
"""

import uuid

from sqlalchemy import func, insert, select, update
from temporalio import activity
from temporalio.exceptions import ApplicationError

from db.engine import engine
from db.models import Run, RunEvent
from workflows.run import RecordInput


@activity.defn(name="record")
async def record(write: RecordInput) -> int:
    run_id = uuid.UUID(write.run_id)
    async with engine().begin() as conn:
        updated = await conn.execute(
            update(Run)
            .where(Run.run_id == run_id, Run.tenant_id == uuid.UUID(write.tenant_id))
            .values(status=write.run_status, updated_at=func.now())
        )
        if updated.rowcount != 1:
            # No row for this run and tenant: a retry cannot fix it, so the run fails now, not after three tries.
            raise ApplicationError(f"run {write.run_id} not found for tenant", non_retryable=True)
        # Steps of one run happen in order, so max+1 is safe; a doubled attempt hits the primary key and retries.
        next_seq = select(func.coalesce(func.max(RunEvent.seq), 0) + 1).where(RunEvent.run_id == run_id)
        seq = await conn.scalar(
            insert(RunEvent)
            .values(run_id=run_id, seq=next_seq.scalar_subquery(), stage=write.stage, status=write.stage_status, text=write.text)
            .returning(RunEvent.seq)
        )
        await conn.execute(select(func.pg_notify(f"run_{write.run_id}", str(seq))))
    activity.logger.info("recorded", extra={"run_id": write.run_id, "run_status": write.run_status, "seq": seq})
    return seq
