"""The researcher's three providers, real: Tavily for pages, OpenAI for rows, httpx for the page check.

Each is a class whose method has the shape `activities.research` expects, so a test replaces it with a fake. Timeouts,
retries and backoff are the design's dependency table (§8): Tavily 20 s, two retries from 1 s; OpenAI 60 s, three
retries honouring Retry-After, done by its client; a page fetch 10 s, no retry.
"""

import asyncio

import httpx
from bs4 import BeautifulSoup
from openai import AsyncOpenAI
from tavily import AsyncTavilyClient
from tavily.errors import UsageLimitExceededError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from activities.research import Extracted, SearchUnavailable
from contracts.researcher import ExtractInput, Page, Rows
from settings import settings

SEARCH_TIMEOUT = 20
FETCH_TIMEOUT = 10
MODEL_TIMEOUT = 60
# A browser's name, so a site serves the page it serves a visitor.
FETCH_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FounderAlly/0.1; +https://founderally.app)"}


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
        answer = await self.client.responses.parse(model=self.model, instructions=prompt, input=user, text_format=Rows)
        return Extracted(
            rows=answer.output_parsed,
            tokens_in=answer.usage.input_tokens if answer.usage else 0,
            tokens_out=answer.usage.output_tokens if answer.usage else 0,
        )


class HttpFetch:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True, headers=FETCH_HEADERS)

    async def fetch(self, url: str) -> str | None:
        try:
            response = await self.client.get(url)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        return BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)


def real_researcher():
    """The activity wired to the world. Fails at worker start when a key is missing, not at the first run."""
    from activities.research import Researcher

    s = settings()
    if not s.tavily_api_key or not s.openai_api_key:
        raise RuntimeError("TAVILY_API_KEY and OPENAI_API_KEY are required to run the researcher")
    return Researcher(
        search=TavilySearch(s.tavily_api_key).search,
        extract=OpenAIExtract(s.openai_api_key, s.openai_model).extract,
        fetch=HttpFetch().fetch,
    )
