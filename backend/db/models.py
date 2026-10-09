"""The two tables of a run. `runs` is our own row per Start; `run_events` is its history as the owner sees it.

Temporal keeps the same run as a workflow history; `run_id` is the one id joining our row and that history.
The API inserts a run as `queued`; after that only the `record` activity writes here.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RunEvent(Base):
    __tablename__ = "run_events"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.run_id"), primary_key=True)
    # The order; a reconnecting page sends the last seq it has to get only what it missed.
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Which stage the line belongs to (start, review; later research, retrieve, write) and that stage's status
    # in Temporal's words: started, progress, completed, failed, canceled.
    stage: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
