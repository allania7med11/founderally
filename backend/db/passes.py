"""The five writes and reads of one research pass, each one statement. The activity decides; this touches the table.

Every write is conditional on the column still being null, because two attempts of one pass may run at once
(`activities/research.py` says why). A write that changed nothing is the signal that another attempt wrote first.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from contracts.researcher import Page, Row, Verdict
from db.engine import engine
from db.models import Competitor, ResearchPass


@dataclass(frozen=True)
class PassKey:
    run_id: uuid.UUID
    tenant_id: uuid.UUID
    round: int
    pass_no: int


@dataclass(frozen=True)
class PassRow:
    """What a pass has saved so far; a column still None is a step still to do."""

    pages: list | None
    candidates: list | None
    verdicts: list | None
    rows_found: int | None
    reason: str | None


async def read_pass(key: PassKey) -> PassRow | None:
    """The row, every column, or None. `pages` is deferred in the ORM, so the columns are named."""
    read = select(
        ResearchPass.pages,
        ResearchPass.candidates,
        ResearchPass.verdicts,
        ResearchPass.rows_found,
        ResearchPass.reason,
    ).where(
        ResearchPass.run_id == key.run_id,
        ResearchPass.round == key.round,
        ResearchPass.pass_no == key.pass_no,
    )

    async with engine().connect() as conn:
        result = await conn.execute(read)
        row = result.one_or_none()

    if row is None:
        return None
    return PassRow(
        pages=row.pages,
        candidates=row.candidates,
        verdicts=row.verdicts,
        rows_found=row.rows_found,
        reason=row.reason,
    )


async def insert_pass(key: PassKey, pages: list[Page], reason: str | None) -> None:
    """The row is inserted with its pages. Another attempt that inserted first keeps its pages: on conflict, nothing."""
    async with engine().begin() as conn:
        await conn.execute(
            pg_insert(ResearchPass)
            .values(
                run_id=key.run_id,
                round=key.round,
                pass_no=key.pass_no,
                tenant_id=key.tenant_id,
                pages=[p.model_dump(mode="json") for p in pages],
                reason=reason,
            )
            .on_conflict_do_nothing()
        )


async def set_candidates(key: PassKey, candidates: list[Row], reason: str | None) -> None:
    """The model's answer, written once: only where `candidates` is still null."""
    no_answer_yet = ResearchPass.candidates.is_(None)
    save = (
        update(ResearchPass)
        .where(
            ResearchPass.run_id == key.run_id,
            ResearchPass.round == key.round,
            ResearchPass.pass_no == key.pass_no,
            no_answer_yet,
        )
        .values(candidates=[c.model_dump(mode="json") for c in candidates], reason=reason)
    )

    async with engine().begin() as conn:
        await conn.execute(save)


async def close_pass(key: PassKey, verdicts: list[Verdict], kept: list[tuple[Row, Verdict]]) -> bool:
    """Marks the pass done and saves its kept competitors, in one transaction. False: another attempt closed it
    first, and its rows stand."""
    not_closed_yet = ResearchPass.rows_found.is_(None)
    close = (
        update(ResearchPass)
        .where(
            ResearchPass.run_id == key.run_id,
            ResearchPass.round == key.round,
            ResearchPass.pass_no == key.pass_no,
            not_closed_yet,
        )
        .values(verdicts=[v.model_dump() for v in verdicts], rows_found=len(kept))
        .returning(ResearchPass.rows_found)
    )
    competitors = [
        {
            "competitor_id": uuid.uuid4(),
            "run_id": key.run_id,
            "tenant_id": key.tenant_id,
            "round": key.round,
            "pass_no": key.pass_no,
            "name": row.name,
            "offer": row.offer,
            "price": row.price,
            "channel": row.channel,
            "source_url": verdict.source_url,
            "kind": row.kind,
        }
        for row, verdict in kept
    ]

    async with engine().begin() as conn:
        closed = await conn.scalar(close)
        if closed is None:
            return False
        if competitors:
            await conn.execute(insert(Competitor).values(competitors))
        return True


async def competitor_ids(key: PassKey) -> list[str]:
    async with engine().connect() as conn:
        rows = await conn.execute(
            select(Competitor.competitor_id)
            .where(
                Competitor.run_id == key.run_id,
                Competitor.round == key.round,
                Competitor.pass_no == key.pass_no,
            )
            .order_by(Competitor.created_at, Competitor.name)
        )
        return [str(r[0]) for r in rows]
