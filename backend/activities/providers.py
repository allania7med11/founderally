"""The researcher's two providers, real: Tavily for pages, OpenAI for rows.

Each is a class whose method has the shape `activities.research` expects, so a test replaces it with a fake. Timeouts,
retries and backoff: Tavily 20 s, two retries from 1 s; OpenAI 60 s, three retries honouring Retry-After, done by its
client.
"""

import asyncio

import httpx
from contracts.researcher import ExtractInput, Page, Rows
from openai import AsyncOpenAI
from pydantic import ValidationError
from settings import settings
from tavily import AsyncTavilyClient
from tavily.errors import UsageLimitExceededError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from activities.research import Extracted, SearchUnavailable

SEARCH_TIMEOUT = 20
MODEL_TIMEOUT = 60


class TavilySearch:
    def __init__(self, api_key: str) -> None:
        self.client = AsyncTavilyClient(api_key=api_key)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1),
        # A 429 is Tavily's rate limit: worth the wait. A bad key or an empty quota is not.
        retry=retry_if_exception_type((httpx.HTTPError, TimeoutError, UsageLimitExceededError)),
        reraise=True,
    )
    async def _call(self, query: str, max_results: int) -> dict:
        return await asyncio.wait_for(
            self.client.search(query=query, max_results=max_results, include_raw_content=True),
            timeout=SEARCH_TIMEOUT,
        )

    async def search(self, query: str, max_results: int) -> list[Page]:
        try:
            answer = await self._call(query, max_results)
        except Exception as e:  # noqa: BLE001 - whatever Tavily raises after its retries: the pass goes on with no pages
            raise SearchUnavailable(str(e)) from e
        return [
            Page(url=r["url"], title=r.get("title") or r["url"], text=r.get("raw_content") or r.get("content") or "")
            for r in answer.get("results", [])
            if r.get("url")
        ]


class OpenAIExtract:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key, timeout=MODEL_TIMEOUT, max_retries=3)
        self.model = model

    async def extract(self, input: ExtractInput, prompt: str, error: str | None) -> Extracted:
        pages = "\n\n".join(
            f"Page {i}: {p.title} ({p.url})\n{p.text}" for i, p in enumerate(input.pages, start=1)
        )
        user = f"Idea: {input.idea}\nPlace: {input.place}\n\n{pages}"
        if error:
            user += f"\n\nYour previous answer was rejected: {error}. Answer again."
        try:
            answer = await self.client.responses.parse(
                model=self.model, instructions=prompt, input=user, text_format=Rows
            )
        except ValidationError:
            # A cut-off or broken answer, already paid: an invalid answer, never a retry of the node, which would pay
            # again on every try. The tokens are lost with the answer.
            return Extracted(rows=None, tokens_in=0, tokens_out=0)
        return Extracted(
            rows=answer.output_parsed,
            tokens_in=answer.usage.input_tokens if answer.usage else 0,
            tokens_out=answer.usage.output_tokens if answer.usage else 0,
        )


def real_researcher():
    """The activity wired to the world. Fails at worker start when a key is missing, not at the first run."""
    from activities.research import Researcher

    s = settings()
    if not s.tavily_api_key or not s.openai_api_key:
        raise RuntimeError("TAVILY_API_KEY and OPENAI_API_KEY are required to run the researcher")
    return Researcher(
        search=TavilySearch(s.tavily_api_key).search,
        extract=OpenAIExtract(s.openai_api_key, s.openai_model).extract,
    )
