"""What one pass of the researcher decides, on the real tables with Tavily and the model faked. Needs
Postgres (`make up`, `make migrate`), no keys, no Temporal."""

import pytest
from temporalio.testing import ActivityEnvironment

from activities.research import Researcher
from contracts.researcher import PAGE_TEXT_CHARS, Page, Rows
from db.models import MODEL_ANSWER_INVALID, SEARCH_UNAVAILABLE
from tests.cat_cafe import BRIEF, MODEL_ROWS, PAGES
from tests.research_fakes import FakeProviders, competitors, new_run, pass_row
from workflows.run import ResearchInput

pytestmark = pytest.mark.stack


async def test_three_rows_survive_and_kitty_corner_is_dropped() -> None:
    """Search returns the ten café pages. The model names four businesses: Chats Café, Paws & Beans, Le Chat Noir and
    Kitty Corner. The first three are on the pages they cite; Kitty Corner is cited on page 3, which never names it.
    Code keeps three, drops Kitty Corner."""
    run_id, tenant_id = await new_run()
    providers = FakeProviders(pages=PAGES, answers=[MODEL_ROWS])
    researcher = Researcher(search=providers.search, extract=providers.extract)
    first_pass = ResearchInput(run_id=run_id, tenant_id=tenant_id, brief=BRIEF, round=1, pass_no=1)

    out = await ActivityEnvironment().run(researcher.run, first_pass)

    saved = await competitors(run_id)
    assert [c.name for c in saved] == ["Chats Café", "Le Chat Noir", "Paws & Beans"]
    assert saved[0].source_url == "https://chatscafe.tn/"  # the URL comes from the cited page, never from the model
    assert out.rows_found == 3

    verdicts = (await pass_row(run_id, round=1, pass_no=1)).verdicts
    kitty_corner = next(v for v in verdicts if v["name"] == "Kitty Corner")
    assert kitty_corner["kept"] is False
    assert kitty_corner["reason"] == "name_not_on_page"


async def test_two_invalid_model_answers_give_zero_rows_and_a_reason() -> None:
    """The model gives no parsed answer twice (None, as on a refusal). Code asks once more after the first, then gives
    up: nothing to check, so zero rows, and the reason says the model's answer was invalid."""
    run_id, tenant_id = await new_run()
    providers = FakeProviders(answers=[None, None])
    researcher = Researcher(search=providers.search, extract=providers.extract)
    first_pass = ResearchInput(run_id=run_id, tenant_id=tenant_id, brief=BRIEF, round=1, pass_no=1)

    out = await ActivityEnvironment().run(researcher.run, first_pass)

    assert providers.model_calls == 2
    assert out.rows_found == 0
    assert out.reason == MODEL_ANSWER_INVALID


async def test_valid_answer_with_no_competitor_has_no_reason() -> None:
    """The model answers correctly but finds no competitor: an empty list. That is a valid answer, so code does not
    ask again, and the reason stays empty: unlike the invalid-answer case, nothing went wrong."""
    run_id, tenant_id = await new_run()
    providers = FakeProviders(answers=[Rows(rows=[])])
    researcher = Researcher(search=providers.search, extract=providers.extract)
    first_pass = ResearchInput(run_id=run_id, tenant_id=tenant_id, brief=BRIEF, round=1, pass_no=1)

    out = await ActivityEnvironment().run(researcher.run, first_pass)

    assert providers.model_calls == 1
    assert out.rows_found == 0
    assert out.reason is None


async def test_page_number_outside_the_pages_is_re_asked_once_then_dropped() -> None:
    """Search returns ten pages; the model cites page 42, twice. Code rejects a page that was never given, asks once
    more with the error, then gives up: zero rows, model answer invalid."""
    run_id, tenant_id = await new_run()
    row_on_page_42 = MODEL_ROWS.rows[0].model_copy(update={"page_no": 42})
    providers = FakeProviders(answers=[Rows(rows=[row_on_page_42]), Rows(rows=[row_on_page_42])])
    researcher = Researcher(search=providers.search, extract=providers.extract)
    first_pass = ResearchInput(run_id=run_id, tenant_id=tenant_id, brief=BRIEF, round=1, pass_no=1)

    out = await ActivityEnvironment().run(researcher.run, first_pass)

    assert providers.model_calls == 2
    assert out.rows_found == 0
    assert out.reason == MODEL_ANSWER_INVALID


async def test_search_down_closes_the_pass_without_the_model() -> None:
    """Tavily is down after its retries. Code saves the pass with no pages and the reason, never calls the model, and
    a second call reads the closed pass back instead of searching again."""
    run_id, tenant_id = await new_run()
    providers = FakeProviders(search_down=True)
    researcher = Researcher(search=providers.search, extract=providers.extract)
    first_pass = ResearchInput(run_id=run_id, tenant_id=tenant_id, brief=BRIEF, round=1, pass_no=1)

    out = await ActivityEnvironment().run(researcher.run, first_pass)
    await ActivityEnvironment().run(researcher.run, first_pass)

    assert out.reason == SEARCH_UNAVAILABLE
    assert providers.model_calls == 0
    assert providers.search_calls == 2  # two angles, in the first call only


async def test_pass_two_runs_with_twenty_four_pages() -> None:
    """Pass 2 is the wider retry: 24 pages in total, 12 per angle. Search has thirty to give, so the model gets 24."""
    run_id, tenant_id = await new_run()
    thirty_pages = [Page(url=f"https://cafe{i}.example/", title=f"Café {i}", text=f"Café {i}") for i in range(30)]
    providers = FakeProviders(pages=thirty_pages)
    researcher = Researcher(search=providers.search, extract=providers.extract)
    second_pass = ResearchInput(run_id=run_id, tenant_id=tenant_id, brief=BRIEF, round=1, pass_no=2)

    await ActivityEnvironment().run(researcher.run, second_pass)

    # What our code asked search for: 24 pages split over the brief's two angles, "cat café" and
    # "pet-friendly café", 12 each.
    assert providers.max_results_asked == [12, 12]
    # What the model read on its one call (the default answer is valid, so no second call): all 24 pages.
    assert len(providers.seen_by_model[0].pages) == 24


async def test_stored_pages_are_what_the_model_saw_after_the_cap() -> None:
    """Every page is longer than the cap. Code cuts each to PAGE_TEXT_CHARS before storing it and before the model
    reads it, so the stored text is exactly what the model saw."""
    run_id, tenant_id = await new_run()
    too_long = "x" * (PAGE_TEXT_CHARS + 500)
    providers = FakeProviders(pages=[page.model_copy(update={"text": too_long}) for page in PAGES])
    researcher = Researcher(search=providers.search, extract=providers.extract)
    first_pass = ResearchInput(run_id=run_id, tenant_id=tenant_id, brief=BRIEF, round=1, pass_no=1)

    await ActivityEnvironment().run(researcher.run, first_pass)

    stored = (await pass_row(run_id, round=1, pass_no=1)).pages
    seen = providers.seen_by_model[0].pages
    assert len(stored) == len(seen)
    for stored_page, seen_page in zip(stored, seen):
        assert stored_page["text"] == seen_page.text
        assert len(stored_page["text"]) == PAGE_TEXT_CHARS
