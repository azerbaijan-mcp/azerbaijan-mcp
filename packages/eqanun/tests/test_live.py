"""Contract tests against the real site. Run with `uv run pytest -m live`.

They send about ten requests, a second apart, and read one file of about 10 MB. The Civil Code
(id 46944) is the pinned act: a code that is amended now and then, never removed.
"""

import pytest

from azerbaijan_mcp_eqanun import acts, listing
from azerbaijan_mcp_eqanun.client import EqanunClient
from azerbaijan_mcp_eqanun.errors import NotFound

pytestmark = [pytest.mark.live, pytest.mark.anyio]

CIVIL_CODE = 46944


@pytest.fixture
async def eqanun():
    client = EqanunClient()
    yield client
    await client.aclose()


async def test_the_live_search_still_answers_the_way_the_client_reads_it(eqanun):
    kinds = listing.resolve_types((await eqanun.types()).value, "məcəllə")
    assert kinds
    total, found = (await eqanun.search("mülki", type_ids=tuple(k.id for k in kinds))).value
    assert total >= 2
    civil = next(act for act in found if act.id == CIVIL_CODE)
    assert civil.title == "Azərbaycan Respublikasının Mülki Məcəlləsi"
    assert (civil.status, civil.accept_date) == ("in_force", "1999-12-28")
    in_text, _ = (await eqanun.search("iddia müddəti", field="text", length=1)).value
    assert in_text > 100
    repealed, rows = (await eqanun.search("mülki məcəllə", status="repealed", length=2)).value
    assert repealed >= 1
    assert rows
    assert all(row.status == "repealed" for row in rows)


async def test_the_pinned_act_still_has_its_requisites_and_editions(eqanun):
    meta = (await eqanun.framework(CIVIL_CODE)).value
    assert meta.summary.title == "Azərbaycan Respublikasının Mülki Məcəlləsi"
    assert meta.summary.status == "in_force"
    assert meta.summary.accept_date == "1999-12-28"
    assert listing.file_path(meta.html_url).endswith(f"f_{CIVIL_CODE}.html")
    versions = (await eqanun.versions(CIVIL_CODE)).value
    assert len(versions) >= 10
    assert all(version.effective_date for version in versions)


async def test_the_pinned_file_still_parses_into_articles_and_notes(eqanun):
    fetched = await eqanun.act(CIVIL_CODE)
    act = fetched.value
    numbers = [article.number for article in act.articles]
    assert len(numbers) >= 1400
    assert numbers[0] == "1"
    assert len(numbers) == len(set(numbers))
    assert len(act.notes) >= 900
    markers = {
        int(found) for paragraph in act.paragraphs for found in acts.TOKEN.findall(paragraph)
    }
    assert markers <= set(act.notes)
    view = acts.article_view(act, "1")
    assert "məqsəd" in view.heading
    assert view.notes
    # the lists of amending laws and of court decisions after the last article are not part of it
    last = act.articles[-1]
    assert sum(len(p) for p in act.paragraphs[last.start : last.end]) < 10_000
    assert any(part for part in act.links)
    total, matches = acts.search_act(act, "iddia müddəti", 5)
    assert total >= 10
    assert matches[0].article


async def test_an_unknown_act_is_still_reported_as_not_found(eqanun):
    with pytest.raises(NotFound):
        await eqanun.framework(999999999)
