"""The two tables of a run. `runs` is our own row per Start; `run_events` is its history as the owner sees it.

Temporal keeps the same run as a workflow history; `run_id` is the one id joining our row and that history.
The API inserts a run as `queued`; after that only the `record` activity writes here.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Run status, one word, in the order a run moves. The workflow writes these words through `record`.
QUEUED = "queued"
RUNNING = "running"
FAILED = "failed"
CANCELLED = "cancelled"
AWAITING_REVIEW = "awaiting_review"
SAVED = "saved"
DISCARDED = "discarded"


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # Who owns the data: the business, not a login. Every read or signal loads by (run_id, tenant_id).
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # The conversation and the brief this run came from. No `threads` or `briefs` table yet, so no foreign key.
    thread_id: Mapped[uuid.UUID]
    brief_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(Text)
    # The seq of the run's latest line, 0 before the first. `record` bumps it in the same statement that writes the
    # status; that update is also the lock that keeps two writers from taking the same seq.
    last_seq: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "activity_id"),)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.run_id"), primary_key=True)
    # The order rows were saved, `runs.last_seq` after its bump; a reconnecting page sends the last seq it has to
    # get only what it missed.
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Temporal's id for the activity execution that wrote the line, the same on every retry of it; a retried write
    # finds its row by (run_id, activity_id).
    activity_id: Mapped[str] = mapped_column(Text)
    # Which stage the line belongs to (start, review; later research, retrieve, write) and that stage's status
    # in Temporal's words: started, progress, completed, failed, canceled.
    stage: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
