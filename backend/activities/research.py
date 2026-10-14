"""`research`, the activity that finds verified competitors for one pass: search, extract, verify, save.

The pass row (`research_passes`) fills forward as the work goes, each column set once by a conditional write.
Temporal runs an activity at least once, and a retry after a missed heartbeat can start while the first attempt is
still alive: neither can prove the other dead, so the row is the fence. Every attempt reads the row first and does
only what is still null; the last write, `rows_found`, is the gate before `competitors`, so two attempts never
insert the same rows twice. The search and the model are the paid calls; a row that already has their result is
never paid for again. The statements themselves are in `db/passes.py`.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from temporalio import activity
from temporalio.exceptions import ApplicationError

from activities.heartbeat import heartbeating
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
from workflows.run import ResearchInput, ResearchOutput

# Pages in total, the first pass then the wider retry, shared evenly by the angles: 12 and 24 divide by 2, 3 and 4.
PAGES_TOTAL = {1: 12, 2: 24}
# Pages fetched at once in the verify step.
FETCH_AT_ONCE = 6
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


# The three things the activity needs from outside (Tavily, the model, the web), each one callable so a test hands
# in a fake.
Search = Callable[[str, int], Awaitable[list[Page]]]
Extract = Callable[[ExtractInput, str, str | None], Awaitable[Extracted]]
Fetch = Callable[[str], Awaitable[str | None]]


def pass_state(row: PassRow | None) -> PassState:
    """Where a pass stopped, read from which columns are still null. `rows_found` is set last, so set means done."""
    if row is None:
        return "absent"
    if row.rows_found is not None:
        return "done"
    if row.candidates is not None:
        return "candidates"
    return "pages"


class Researcher:
    """The activity as a method, so the providers are given once at worker start and faked in tests."""

    def __init__(self, search: Search, extract: Extract, fetch: Fetch) -> None:
        self.search = search
        self.extract = extract
        self.fetch = fetch

    @activity.defn(name="research")
    async def run(self, input: ResearchInput) -> ResearchOutput:
        if not input.brief.a_angles:
            raise ApplicationError("brief has no angles", non_retryable=True)
        async with heartbeating():
            return await self._run(input)

    async def _run(self, input: ResearchInput) -> ResearchOutput:
        """The five steps, each entered only if the row says it is still to do."""
        key = PassKey(uuid.UUID(input.run_id), uuid.UUID(input.tenant_id), input.round, input.pass_no)
        tokens_in = tokens_out = 0
        row = await read_pass(key)
        if pass_state(row) == "absent":
            await self._search(input, key)
            row = await read_pass(key)
        if pass_state(row) == "pages":
            pages = [Page.model_validate(p) for p in row.pages]
            if pages:
                candidates, tokens_in, tokens_out = await self._extract(input.brief, pages)
                if candidates is None:
                    await set_candidates(key, [], MODEL_ANSWER_INVALID)
                else:
                    await set_candidates(key, candidates, None)
            else:
                # Search gave nothing: no model call, the pass closes with the search's reason.
                await set_candidates(key, [], row.reason)
            row = await read_pass(key)
        if pass_state(row) == "candidates":
            pages = [Page.model_validate(p) for p in row.pages]
            candidates = [Row.model_validate(c) for c in row.candidates]
            verdicts = await self._verify(pages, candidates)
            kept = [(c, v) for c, v in zip(candidates, verdicts) if v.kept]
            await close_pass(key, verdicts, kept)
            row = await read_pass(key)
        ids = await competitor_ids(key)
        activity.logger.info(
            "research pass done",
            extra={"run_id": input.run_id, "round": input.round, "pass": input.pass_no, "rows_found": row.rows_found},
        )
        return ResearchOutput(ids, row.rows_found, row.reason, tokens_in, tokens_out)

    async def _search(self, input: ResearchInput, key: PassKey) -> None:
        """One search per angle, the place appended, each angle an even share of the total; the unique URLs in angle
        order; the row inserted with them. Search still down after its retries: zero pages and the reason, the model is
        never called."""
        share = PAGES_TOTAL[input.pass_no] // len(input.brief.a_angles)
        try:
            per_angle = await asyncio.gather(
                *(
                    self.search(f"{angle} {input.brief.place}", share)
                    for angle in input.brief.a_angles
                )
            )
        except SearchUnavailable:
            await insert_pass(key, [], SEARCH_UNAVAILABLE)
            return
        pages: list[Page] = []
        seen: set[str] = set()
        for found in per_angle:
            for page in found:
                if str(page.url) not in seen and len(pages) < PAGES_TOTAL[input.pass_no]:
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

    async def _verify(self, pages: list[Page], candidates: list[Row]) -> list[Verdict]:
        """Code opens each cited page itself, once per page: it loads and the name is on it, or the row is dropped."""
        at_once = asyncio.Semaphore(FETCH_AT_ONCE)

        async def load(url: str) -> str | None:
            async with at_once:
                return await self.fetch(url)

        # Two candidates on one guide page share one fetch.
        cited = list(dict.fromkeys(str(pages[c.page_no - 1].url) for c in candidates if 1 <= c.page_no <= len(pages)))
        texts = dict(zip(cited, await asyncio.gather(*(load(url) for url in cited))))

        def check(candidate: Row) -> Verdict:
            if not 1 <= candidate.page_no <= len(pages):
                url, reason = None, "page_no_out_of_range"
            else:
                url = str(pages[candidate.page_no - 1].url)
                text = texts[url]
                if text is None:
                    reason = "page_failed_to_load"
                elif candidate.name.casefold() not in text.casefold():
                    reason = "name_not_on_page"
                else:
                    reason = None
            return Verdict(
                page_no=candidate.page_no, name=candidate.name, source_url=url, kept=reason is None, reason=reason
            )

        return [check(c) for c in candidates]
