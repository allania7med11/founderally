"""`record`, the one activity that writes about a run. The workflow decides where the run is; this writes it.

One call, one transaction, three writes: the run's new status and next seq, one event line under that seq, and a
NOTIFY so the API can push the line to the page. Temporal runs an activity at least once: a worker that commits
and dies before reporting is retried, with the same `activity_id`. The transaction makes a call whole; the key
`(run_id, activity_id)` makes a repeat write nothing. seq is given here, at save time, so it is the order rows
were saved even when two steps run at once.
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
    activity_id = activity.info().activity_id
    async with engine().begin() as conn:
        # Saved before, failed to report: a worker that committed this write and died before telling Temporal is
        # retried with the same activity_id. The row is there, so hand back its seq and do nothing again.
        saved = await conn.scalar(
            select(RunEvent.seq).where(RunEvent.run_id == run_id, RunEvent.activity_id == activity_id)
        )
        if saved is not None:
            activity.logger.info("already recorded", extra={"run_id": write.run_id, "seq": saved})
            return saved
        # The run row is the stream: one update bumps its seq and writes the status, and holds the row until
        # commit, so no two writers can take the same seq. No row for this run and tenant gives None.
        seq = await conn.scalar(
            update(Run)
            .where(Run.run_id == run_id, Run.tenant_id == uuid.UUID(write.tenant_id))
            .values(last_seq=Run.last_seq + 1, status=write.run_status, updated_at=func.now())
            .returning(Run.last_seq)
        )
        if seq is None:
            # A retry cannot fix a missing row, so the run fails now.
            raise ApplicationError(f"run {write.run_id} not found for tenant", non_retryable=True)
        # The unique key on (run_id, activity_id) is the guard if the lookup above missed an uncommitted twin: this
        # insert fails, the whole transaction rolls back, Temporal retries, the retry finds the row.
        await conn.execute(
            insert(RunEvent).values(
                run_id=run_id,
                seq=seq,
                activity_id=activity_id,
                stage=write.stage,
                status=write.stage_status,
                text=write.text,
            )
        )
        await conn.execute(select(func.pg_notify(f"run_{write.run_id}", str(seq))))
    activity.logger.info("recorded", extra={"run_id": write.run_id, "run_status": write.run_status, "seq": seq})
    return seq
