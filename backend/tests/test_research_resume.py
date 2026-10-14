"""Nothing paid runs twice: a second call, a retry after a crash and two attempts at once all read back what the
first one saved. Needs Postgres (`make up`, `make migrate`), no keys, no Temporal."""

import asyncio

import pytest
from temporalio.testing import ActivityEnvironment

from activities.research import Researcher
from db.models import MODEL_ANSWER_INVALID
from tests.cat_cafe import BRIEF, MODEL_ROWS, PAGES
from tests.research_fakes import FakeProviders, competitors, new_run
from workflows.run import ResearchInput

pytestmark = pytest.mark.stack


async def test_second_call_reads_back_and_pays_nothing() -> None:
    """The same pass is called twice, as after a Temporal retry. The first call searches, asks the model and saves; the
    second finds the pass done and only reads the saved ids back: no search, no model, no tokens."""
    run_id, tenant_id = await new_run()
    providers = FakeProviders(pages=PAGES, answers=[MODEL_ROWS])
    researcher = Researcher(search=providers.search, extract=providers.extract, fetch=providers.fetch)
    # One input for both calls: same run, round and pass, so the second call is the same step run again.
    same_pass = ResearchInput(run_id=run_id, tenant_id=tenant_id, brief=BRIEF, round=1, pass_no=1)

    first = await ActivityEnvironment().run(researcher.run, same_pass)
    second = await ActivityEnvironment().run(researcher.run, same_pass)

    assert providers.search_calls == 2  # two angles, in the first call only
    assert providers.model_calls == 1
    assert second.competitor_ids == first.competitor_ids
    assert second.tokens_in == 0


async def test_zero_rows_pass_also_reads_back() -> None:
    """A pass that ended with zero rows is done too: the second call reads it back and does not ask the model again."""
    run_id, tenant_id = await new_run()
    providers = FakeProviders(answers=[None, None])
    researcher = Researcher(search=providers.search, extract=providers.extract, fetch=providers.fetch)
    # One input for both calls: same run, round and pass, so the second call is the same step run again.
    same_pass = ResearchInput(run_id=run_id, tenant_id=tenant_id, brief=BRIEF, round=1, pass_no=1)

    await ActivityEnvironment().run(researcher.run, same_pass)
    again = await ActivityEnvironment().run(researcher.run, same_pass)

    assert providers.model_calls == 2  # both in the first call
    assert again.reason == MODEL_ANSWER_INVALID


async def test_model_failure_then_retry_sees_the_same_pages_and_searches_once() -> None:
    """The first attempt searches and saves the pages, then the model fails with a 500. The retry finds the pages
    saved, skips the search, and the model reads exactly the same pages."""
    run_id, tenant_id = await new_run()
    providers = FakeProviders(pages=PAGES, answers=[RuntimeError("model: 500"), MODEL_ROWS])
    researcher = Researcher(search=providers.search, extract=providers.extract, fetch=providers.fetch)
    # One input for both calls: same run, round and pass, so the second call is the same step run again.
    same_pass = ResearchInput(run_id=run_id, tenant_id=tenant_id, brief=BRIEF, round=1, pass_no=1)

    with pytest.raises(RuntimeError):
        await ActivityEnvironment().run(researcher.run, same_pass)
    out = await ActivityEnvironment().run(researcher.run, same_pass)

    # Two searches, one per angle, in the first attempt only; the retry reads the stored pages.
    assert providers.search_calls == 2
    assert providers.seen_by_model[0].pages == providers.seen_by_model[1].pages
    assert out.rows_found == 3


async def test_two_attempts_of_one_pass_write_one_set_of_competitors() -> None:
    """Two attempts of one pass run at the same time, as when Temporal retries while the first is still alive. Every
    write is "only if still empty", so one attempt saves and the other reads its result: three competitors, not six."""
    run_id, tenant_id = await new_run()
    providers = FakeProviders(pages=PAGES, answers=[MODEL_ROWS])
    researcher = Researcher(search=providers.search, extract=providers.extract, fetch=providers.fetch)
    # One input for both calls: same run, round and pass, so the second call is the same step run again.
    same_pass = ResearchInput(run_id=run_id, tenant_id=tenant_id, brief=BRIEF, round=1, pass_no=1)

    first, second = await asyncio.gather(
        ActivityEnvironment().run(researcher.run, same_pass),
        ActivityEnvironment().run(researcher.run, same_pass),
    )

    assert first.competitor_ids == second.competitor_ids
    assert len(await competitors(run_id)) == 3
