import pytest

from azerbaijan_mcp_azstat import catalogue
from azerbaijan_mcp_azstat.errors import UnexpectedShape


def body(*rows):
    return {"success": True, "count": len(rows), "data": list(rows)}


def row(table_id, name, description="", section_id="994_002", section_name="Labour market"):
    return {
        "table_id": table_id,
        "table_name": name,
        "description": description,
        "section_id": section_id,
        "section_name": section_name,
    }


@pytest.fixture
def english(load):
    return catalogue.parse_catalogue(load("tables_en.json"), "en")


@pytest.fixture
def azerbaijani(load):
    return catalogue.parse_catalogue(load("tables_az.json"), "az")


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("Gəlir", "gelir"),
        ("ƏHALİ", "ehali"),
        ("Şirkət", "sirket"),
        ("ığ", "ig"),
        ("ÖĞRƏNCİ", "ogrenci"),
        ("Café", "cafe"),
        ("Plain", "plain"),
    ],
)
def test_fold_lowercases_and_strips_accents(text, folded):
    assert catalogue.fold(text) == folded


def test_catalogue_entries_carry_name_description_and_topic(english):
    by_id = {entry.table_id: entry for entry in english}
    population = by_id["DT_AA_001"]
    assert population.name == "Population size (at the beginning of year)"
    assert population.description.startswith("This dataset presents statistical data")
    assert (population.topic_id, population.topic) == ("994_001", "Demographic indicators")
    assert by_id["DT_BB_001"].description == ""
    assert by_id["DT_AC_068"].description.count("  ") == 0


def test_the_unnamed_first_topic_gets_a_name_in_both_languages(azerbaijani):
    assert catalogue.topics(azerbaijani)[0] == catalogue.TopicCount(
        "994_001", "Demoqrafik göstəricilər", 1
    )
    unnamed = catalogue.parse_catalogue(
        body(row("DT_X_1", "X", section_id="994_099", section_name=None)), "en"
    )
    assert unnamed[0].topic == "994_099"


def test_topics_are_counted_and_sorted_by_id(english):
    topics = catalogue.topics(english)
    assert [t.id for t in topics] == sorted(t.id for t in topics)
    assert sum(t.tables for t in topics) == len(english)
    assert {t.id: t.name for t in topics}["994_002"] == "Labour market"


def test_a_topic_is_found_by_id_or_by_part_of_its_name(english, azerbaijani):
    assert catalogue.resolve_topics(english, "994_003") == {"994_003"}
    assert catalogue.resolve_topics(english, "LABOUR") == {"994_002"}
    assert catalogue.resolve_topics(azerbaijani, "emek") == {"994_002"}
    assert catalogue.resolve_topics(english, "no such topic") == set()
    assert catalogue.resolve_topics(english, "  ") == set()


def test_every_word_must_appear_and_titles_outrank_descriptions():
    entries = catalogue.parse_catalogue(
        body(
            row("DT_1", "Wages of nurses", "Average pay in hospitals"),
            row("DT_2", "Hospitals", "Wages by region and nurses on duty"),
            row("DT_3", "Schools", "Nothing relevant"),
        ),
        "en",
    )
    found = catalogue.search(entries, "nurses wages")
    assert [e.table_id for e in found] == ["DT_1", "DT_2"]
    assert catalogue.search(entries, "nurses teachers") == []


def test_an_exact_phrase_in_the_title_ranks_first():
    entries = catalogue.parse_catalogue(
        body(row("DT_1", "Price of oil and gas"), row("DT_2", "Gas and oil price index")), "en"
    )
    assert [e.table_id for e in catalogue.search(entries, "oil and gas")] == ["DT_1", "DT_2"]


def test_search_without_a_query_lists_the_topic_by_id(english):
    ids = catalogue.resolve_topics(english, "994_003")
    found = catalogue.search(english, "", ids)
    assert found
    assert [e.table_id for e in found] == sorted(e.table_id for e in found)
    assert {e.topic_id for e in found} == {"994_003"}
    assert len(catalogue.search(english, "")) == len(english)


def test_search_respects_the_topic_filter(english):
    population = catalogue.search(english, "population")
    assert "DT_AA_001" in [e.table_id for e in population]
    narrowed = catalogue.search(english, "population", {"994_001"})
    assert [e.table_id for e in narrowed] == ["DT_AA_001"]


def test_azerbaijani_words_match_with_or_without_diacritics(azerbaijani):
    for query in ("gəlir", "gelir", "GƏLİR"):
        assert [e.table_id for e in catalogue.search(azerbaijani, query)] == ["DT_BA_005"]


@pytest.mark.parametrize(
    "bad",
    [
        {"success": True},
        {"data": {}},
        body({"table_name": "no id"}),
        body({"table_id": "DT_1"}),
        body(None),
    ],
)
def test_a_catalogue_in_another_shape_fails_loudly(bad):
    with pytest.raises(UnexpectedShape):
        catalogue.parse_catalogue(bad, "en")
