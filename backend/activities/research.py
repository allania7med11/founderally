"""A, the researcher: three graph nodes, search, extract and verify, each run as its own activity, for one pass.

The nodes share one row per pass (`research_passes`): search saves the pages, extract the candidates, verify the
verdicts and `rows_found`. The row also keeps what the model read, for evals.

Temporal runs each node at least once, and a retry after a missed heartbeat can start while the first attempt is
still running. So each node is idempotent: it reads the row first and does only the steps still missing, and every
write is conditional, applied only while its column is still null. Search and the model, the paid calls, are not
repeated once their result is saved, and `competitors` are inserted only in the transaction that sets `rows_found`,
so never twice. The SQL is in `db/passes.py`.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from contracts.brief import Brief
from contracts.researcher import PAGE_TEXT_CHARS, ExtractInput, Page, Row, Rows, Verdict
from db.models import MODEL_ANSWER_INVALID, SEARCH_UNAVAILABLE
from db.passes import (
    PassKey,
    PassRow,
    close_pass,
    competitor_ids,
    insert_pass,
    read_pass,
    set_candidates,
)
from temporalio import activity
from temporalio.exceptions import ApplicationError
from workflows.run import ResearchState

from activities.heartbeat import heartbeating
from activities.names import name_in_text

# Pages in total, the first pass then the wider retry, shared evenly by the angles: 12 and 24 divide by 2, 3 and 4.
PAGES_TOTAL = {1: 12, 2: 24}
# The prompt is a versioned file; its tag goes to LangSmith as metadata of the model call.
PROMPT_VERSION = "extract_v1"
PROMPT = (Path(__file__).parent.parent / "prompts" / f"{PROMPT_VERSION}.md").read_text()

PassState = Literal["absent", "pages", "candidates", "done"]


class SearchUnavailable(Exception):
    """The search provider is still down after its own retries. The pass goes on with zero pages."""


@dataclass
class Extracted:
    """One model answer: the rows, or None when the model gave no parsed answer (a refusal), and what the call cost."""

    rows: Rows | None
    tokens_in: int
    tokens_out: int


# The two things the nodes need from outside (Tavily, the model), each one callable so a test hands in a fake.
Search = Callable[[str, int], Awaitable[list[Page]]]
Extract = Callable[[ExtractInput, str, str | None], Awaitable[Extracted]]


def pass_state(row: PassRow | None) -> PassState:
    """Where a pass stopped, read from which columns are still null. `rows_found` is set last, so set means done."""
    if row is None:
        return "absent"
    if row.rows_found is not None:
        return "done"
    if row.candidates is not None:
        return "candidates"
    return "pages"


def pass_key(state: ResearchState) -> PassKey:
    return PassKey(uuid.UUID(state["run_id"]), uuid.UUID(state["tenant_id"]), state["round"], state["pass_no"])


class Researcher:
    """The three nodes as methods, so the providers are given once at worker start and faked in tests. Each node
    reads the pass row first and does its step only if the row says it is still to do."""

    def __init__(self, search: Search, extract: Extract) -> None:
        self.search = search
        self.extract = extract

    async def search_node(self, state: ResearchState) -> dict:
        """Search, then insert the pass row with the pages."""
        brief = Brief.model_validate(state["brief"])
        if not brief.a_angles:
            raise ApplicationError("brief has no angles", non_retryable=True)
        key = pass_key(state)
        async with heartbeating():
            if pass_state(await read_pass(key)) == "absent":
                await self._search(brief, state["pass_no"], key)
        return {}

    async def extract_node(self, state: ResearchState) -> dict:
        """Ask the model for rows from the saved pages, then save them as candidates."""
        brief = Brief.model_validate(state["brief"])
        key = pass_key(state)
        tokens_in = tokens_out = 0
        async with heartbeating():
            row = await read_pass(key)
            if pass_state(row) == "pages":
                pages = [Page.model_validate(p) for p in row.pages]
                if pages:
                    candidates, tokens_in, tokens_out = await self._extract(brief, pages)
                    if candidates is None:
                        await set_candidates(key, [], MODEL_ANSWER_INVALID)
                    else:
                        await set_candidates(key, candidates, None)
                else:
                    # Search gave nothing: no model call, the pass closes with the search's reason.
                    await set_candidates(key, [], row.reason)
        return {"tokens_in": tokens_in, "tokens_out": tokens_out}

    async def verify_node(self, state: ResearchState) -> dict:
        """Check each candidate's name in its page, close the pass with the kept ones, hand back their ids."""
        key = pass_key(state)
        async with heartbeating():
            row = await read_pass(key)
            if pass_state(row) == "candidates":
                pages = [Page.model_validate(p) for p in row.pages]
                candidates = [Row.model_validate(c) for c in row.candidates]
                verdicts = self._verify(pages, candidates)
                kept = [(c, v) for c, v in zip(candidates, verdicts) if v.kept]
                await close_pass(key, verdicts, kept)
                row = await read_pass(key)
            ids = await competitor_ids(key)
        activity.logger.info(
            "research pass done",
            extra={
                "run_id": state["run_id"],
                "round": state["round"],
                "pass": state["pass_no"],
                "rows_found": row.rows_found,
            },
        )
        return {"competitor_ids": ids, "rows_found": row.rows_found, "reason": row.reason}

    async def _search(self, brief: Brief, pass_no: int, key: PassKey) -> None:
        """One search per angle, the place appended, each angle an even share of the total; the unique URLs in angle
        order; the row inserted with them. Search still down after its retries: zero pages and the reason, the model is
        never called."""
        share = PAGES_TOTAL[pass_no] // len(brief.a_angles)
        searches = [self.search(f"{angle} {brief.place}", share) for angle in brief.a_angles]
        try:
            per_angle = await asyncio.gather(*searches)
        except SearchUnavailable:
            await insert_pass(key, [], SEARCH_UNAVAILABLE)
            return
        pages: list[Page] = []
        seen: set[str] = set()
        for found in per_angle:
            for page in found:
                if str(page.url) not in seen and len(pages) < PAGES_TOTAL[pass_no]:
                    seen.add(str(page.url))
                    pages.append(Page(url=page.url, title=page.title, text=page.text[:PAGE_TEXT_CHARS]))
        await insert_pass(key, pages, None)

    async def _extract(self, brief: Brief, pages: list[Page]) -> tuple[list[Row] | None, int, int]:
        """One model call; no parsed answer or a page outside the pages: once more with the error; then None, so an
        invalid answer is not mistaken for a valid one that found no competitor."""
        extract_input = ExtractInput(idea=brief.idea, place=brief.place, pages=pages)
        tokens_in = tokens_out = 0
        error: str | None = None
        for _ in range(2):
            answer = await self.extract(extract_input, PROMPT, error)
            tokens_in += answer.tokens_in
            tokens_out += answer.tokens_out
            if answer.rows is None:
                error = "the answer did not match the schema"
                continue
            bad = [r.page_no for r in answer.rows.rows if not 1 <= r.page_no <= len(pages)]
            if bad:
                error = f"page_no must be between 1 and {len(pages)}; got {bad}"
                continue
            return answer.rows.rows, tokens_in, tokens_out
        return None, tokens_in, tokens_out

    def _verify(self, pages: list[Page], candidates: list[Row]) -> list[Verdict]:
        """Each candidate's name must be in the stored text of the page it cites, the text the model read: verify
        checks the model, not the web, so no page is downloaded again. `_extract` already rejected a page outside
        the pages."""
        verdicts = []
        for candidate in candidates:
            page = pages[candidate.page_no - 1]
            found = name_in_text(candidate.name, page.text)
            verdicts.append(
                Verdict(
                    page_no=candidate.page_no,
                    name=candidate.name,
                    source_url=str(page.url),
                    kept=found,
                    reason=None if found else "name_not_on_page",
                )
            )
        return verdicts

