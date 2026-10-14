"""The researcher's contract: what code builds for the model, what the model answers, what code keeps.
The model points at a page by its number in the prompt and never writes a URL: a typed URL is a copy, and a copy
can be wrong; a number outside 1..n is caught by code. Code resolves the number back to the stored page and writes
the URL itself.
"""

from typing import Literal

from pydantic import BaseModel, HttpUrl

# Each page's text is cut here, once, before it is stored and before it is prompted: the row and the prompt hold
# the same text.
PAGE_TEXT_CHARS = 8_000


class Page(BaseModel):
    """One page as Tavily returned it, text already cut."""

    url: HttpUrl
    title: str
    text: str


class ExtractInput(BaseModel):
    """What the model is given: the idea, the place, the pages in stored order; page i is "Page i" in the prompt."""

    idea: str
    place: str
    pages: list[Page]


class Row(BaseModel):
    """One competitor as the model read it. Nothing is guessed: a field the page does not give stays empty."""

    name: str
    offer: str | None
    # As written on the page, never converted.
    price: str | None
    channel: Literal["online", "shop", "both"] | None
    # Which page the competitor was found on. The prompt lists the pages as "Page 1", "Page 2", ... in stored
    # order; the model answers that number and code turns it back into the page's URL. Never a URL from the model.
    page_no: int
    kind: Literal["direct", "indirect"]


class Rows(BaseModel):
    rows: list[Row]


class Verdict(BaseModel):
    """Why a candidate is or is not in `competitors`. Written by code after the page check, one per candidate."""

    page_no: int
    source_url: str | None
    name: str
    kept: bool
    reason: Literal["page_no_out_of_range", "page_failed_to_load", "name_not_on_page"] | None
