"""Our tables, in the order a run fills them: the brief, the run, its event lines, the researcher's pass and rows.

Temporal keeps the same run as a workflow history; `run_id` is the one id joining our rows and that history.
The API inserts the brief and the run; after that only activities write here, each to its own rows, under a key
that lets a retry find what is already done.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, deferred, mapped_column

# Run status, one word, in the order a run moves. The workflow writes these words through `record`.
QUEUED = "queued"
RUNNING = "running"
FAILED = "failed"
CANCELLED = "cancelled"
AWAITING_REVIEW = "awaiting_review"
SAVED = "saved"
DISCARDED = "discarded"

# Brief status: the conversation proposes, the Start click confirms. The skeleton inserts confirmed directly.
PROPOSED = "proposed"
CONFIRMED = "confirmed"

# Why a research pass found nothing, when it did; null when it found something or is not done.
SEARCH_UNAVAILABLE = "search_unavailable"
MODEL_ANSWER_INVALID = "model_answer_invalid"


class Base(DeclarativeBase):
    pass


class Brief(Base):
    """One recap of the thread, confirmed by the user; one row per round of a run. The brief JSON never changes;
    status flips proposed -> confirmed on the click, and `run_id` is set when the run takes it."""

    __tablename__ = "briefs"
    # One confirmed brief per round of a run; proposed rows for the same round may pile up before the click.
    __table_args__ = (
        Index(
            "ux_briefs_run_round_confirmed",
            "run_id",
            "round",
            unique=True,
            postgresql_where="status = 'confirmed'",
        ),
    )

    brief_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # No `threads` table yet, so no foreign key. A thread holds more than one run, so (thread, round) is no key.
    thread_id: Mapped[uuid.UUID]
    # The run this brief belongs to. Null while proposed in the conversation: the round 1 brief exists before its
    # run does. Start and the Rerun click set it. The key goes on the many side: one run, one brief per round.
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.run_id"))
    round: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    # The five fields of `contracts.brief.Brief`, as sent.
    brief: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # Who owns the data: the business, not a login. Every read or signal loads by (run_id, tenant_id).
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    thread_id: Mapped[uuid.UUID]
    # The run's brief is a query, not a column: briefs where run_id = ? and round = ? and status = confirmed.
    status: Mapped[str] = mapped_column(Text)
    # 1 at Start, +1 per rerun after feedback; the key every activity's rows carry.
    round: Mapped[int] = mapped_column(Integer, server_default="1")
    # 1 for the first try, 2 for the code retry inside a round. Column `pass`; `pass` is a Python keyword.
    pass_no: Mapped[int] = mapped_column("pass", Integer, server_default="1")
    # What the run has spent so far, summed by `record` from what activities return.
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), server_default="0")
    # The seq of the run's latest line, 0 before the first. `record` bumps it in the same statement that writes the
    # status; that update is also the lock that keeps two writers from taking the same seq.
    last_seq: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "activity_id"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.run_id"), primary_key=True
    )
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ResearchPass(Base):
    """One pass of the researcher, keyed (run_id, round, pass). The row fills forward as the pass runs: the pages
    when the search answers, the model's answer when it answers, the verdicts and count after the page checks.
    Every column after the key starts null and is set once; a retry reads the nulls to see where to resume."""

    __tablename__ = "research_passes"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.run_id"), primary_key=True
    )
    round: Mapped[int] = mapped_column(Integer, primary_key=True)
    pass_no: Mapped[int] = mapped_column("pass", Integer, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # The pages the model was given, `list[Page]`, text already cut: the same bytes it read, so a retry and an eval
    # see what it saw. Deferred: ten pages of text that no read-back needs until the model is called.
    pages: Mapped[list | None] = deferred(mapped_column(JSONB, nullable=True))
    # What the model answered, `Rows` as JSON, before any page check. The model, prompt and tokens of that call are
    # in LangSmith under this run_id, not here.
    candidates: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # One per candidate: source_url, name, kept or dropped, reason. Why a row is or is not in `competitors`.
    verdicts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # How many candidates survived; set last, so "set" means the pass is done.
    rows_found: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # SEARCH_UNAVAILABLE or MODEL_ANSWER_INVALID when the pass had nothing to check; null otherwise.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Competitor(Base):
    """One verified competitor: its name was on the page we opened. Read by (run_id, round, pass); never updated."""

    __tablename__ = "competitors"

    competitor_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.run_id"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    round: Mapped[int] = mapped_column(Integer)
    pass_no: Mapped[int] = mapped_column("pass", Integer)
    name: Mapped[str] = mapped_column(Text)
    offer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # As written on the page, never converted.
    price: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
