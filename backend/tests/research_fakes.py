"""Fake providers for the researcher's tests: Tavily, the model and the web, and readers for what a pass saved."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import insert, select

from activities.research import Extracted, SearchUnavailable
from contracts.researcher import ExtractInput, Page
from db.engine import engine
from db.models import QUEUED, Competitor, ResearchPass, Run
from tests.cat_cafe import MODEL_ROWS, PAGES


@dataclass
class FakeProviders:
    """Stands in for Tavily, the model and the web. A test sets what they return (`pages`, `answers`) and then reads
    what our code sent them (the call counts, `max_results_asked`, `seen_by_model`, `fetched`).

    `answers` is what the model says, one per call; the last one repeats. None is no parsed answer (a refusal); an
    exception is raised."""

    pages: list[Page] = field(default_factory=lambda: list(PAGES))
    answers: list = field(default_factory=lambda: [MODEL_ROWS])
    search_down: bool = False
    search_calls: int = 0
    max_results_asked: list[int] = field(default_factory=list)
    model_calls: int = 0
    seen_by_model: list[ExtractInput] = field(default_factory=list)
    fetched: list[str] = field(default_factory=list)

    async def search(self, query: str, max_results: int) -> list[Page]:
        self.search_calls += 1
        self.max_results_asked.append(max_results)
        if self.search_down:
            raise SearchUnavailable("tavily: 503")
        # The first angle gets the first pages, the second angle the next ones, each at most max_results.
        if "cat" in query:
            return self.pages[:max_results]
        return self.pages[max_results : 2 * max_results]

    async def extract(self, input: ExtractInput, prompt: str, error: str | None) -> Extracted:
        self.model_calls += 1
        self.seen_by_model.append(input)
        answer_index = min(self.model_calls, len(self.answers)) - 1
        answer = self.answers[answer_index]
        if isinstance(answer, Exception):
            raise answer
        return Extracted(rows=answer, tokens_in=1000, tokens_out=100)

    async def fetch(self, url: str) -> str | None:
        self.fetched.append(url)
        for page in self.pages:
            if str(page.url) == url:
                return page.text
        return None


async def new_run() -> tuple[str, str]:
    """An empty run in the table, so the pass has a run to belong to."""
    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    add_run = insert(Run).values(run_id=run_id, tenant_id=tenant_id, thread_id=uuid.uuid4(), status=QUEUED)
    async with engine().begin() as conn:
        await conn.execute(add_run)
    return str(run_id), str(tenant_id)


async def pass_row(run_id: str, round: int, pass_no: int):
    """The saved pass row, or None."""
    read = select(
        ResearchPass.pages,
        ResearchPass.candidates,
        ResearchPass.verdicts,
        ResearchPass.rows_found,
        ResearchPass.reason,
    ).where(
        ResearchPass.run_id == uuid.UUID(run_id),
        ResearchPass.round == round,
        ResearchPass.pass_no == pass_no,
    )
    async with engine().connect() as conn:
        result = await conn.execute(read)
        return result.one_or_none()


async def competitors(run_id: str) -> list:
    """The saved competitors of the run, sorted by name."""
    read = (
        select(
            Competitor.name,
            Competitor.round,
            Competitor.pass_no.label("pass_no"),
            Competitor.source_url,
        )
        .where(Competitor.run_id == uuid.UUID(run_id))
        .order_by(Competitor.name)
    )
    async with engine().connect() as conn:
        result = await conn.execute(read)
        return list(result)
