import copy

import pytest

from azerbaijan_mcp_azstat import tables
from azerbaijan_mcp_azstat.errors import UnexpectedShape


def record(period="2020", value=1.0, categories=(("Indicator", "001", "Total"),), **extra):
    result = {
        "table_id": "DT_X",
        "period_type": "Y",
        "period": period,
        "dataset_title": "Test",
        "value": value,
        "symbol": None,
        "comment": "N",
        "publication_status": "1210110",
    }
    for index, (dimension, level_id, name) in enumerate(categories, 1):
        result[f"dimension_{index}"] = dimension
        result[f"level_{index}_id"] = level_id
        result[f"level_{index}_name"] = name
        result[f"hierarchy_{index}_level_1"] = name
        result[f"hierarchy_{index}_depth"] = 1
    result.update(extra)
    return result


def body(*records):
    meta = {"table_id": "DT_X", "table_name": "Test table"}
    return {"success": True, "table": meta, "count": len(records), "data": list(records)}


@pytest.fixture
def population(load):
    return tables.parse_table(load("data_DT_AA_001.json"))


@pytest.fixture
def civil_service(load):
    return tables.parse_table(load("data_DT_AB_051.json"))


@pytest.fixture
def teachers(load):
    return tables.parse_table(load("data_DT_AC_037.json"))


@pytest.fixture
def monthly(load):
    return tables.parse_table(load("data_DT_BE_119.json"))


def test_a_one_dimension_table_becomes_compact_rows(population):
    assert population.name == "Population size (at the beginning of year)"
    assert population.dimensions == ("Indicator",)
    assert len(population.rows) == 160
    assert population.rows[0] == tables.Row(
        period="1995",
        period_type="Y",
        categories=("Total population",),
        value=7643.5,
        symbol=None,
        unit="thsd.person",
    )
    assert (population.duplicates, population.ambiguous) == (0, False)


def test_a_nested_category_reads_parent_then_child(teachers):
    first = {row.categories[0] for row in teachers.rows}
    second = {row.categories[1] for row in teachers.rows}
    assert "directors: > primary schools" in first
    assert "of them having education > higher" in second
    assert "All teachers (including heads of the schools)" in first


def test_values_symbols_and_units_are_kept_as_published(civil_service, teachers, population):
    empty = [row for row in civil_service.rows if row.value is None]
    assert empty
    assert {row.symbol for row in empty} == {"-"}
    assert any(row.value == 13756 and isinstance(row.value, int) for row in civil_service.rows)
    assert any(isinstance(row.value, float) for row in population.rows)
    assert {row.unit for row in teachers.rows} == {None, "percent"}
    assert {row.unit for row in population.rows} == {"thsd.person"}


def test_a_monthly_table_keeps_its_period_type_and_period_text(monthly):
    assert {row.period_type for row in monthly.rows} == {"M"}
    assert monthly.rows[0].period == "202601"


def test_rows_that_share_period_and_categories_make_the_table_ambiguous(load):
    table = tables.parse_table(load("data_DT_AC_011.json"))
    assert table.ambiguous
    assert table.duplicates == len(table.rows) == 60


def test_a_unit_or_a_period_type_sets_otherwise_equal_rows_apart():
    apart = body(record(unit="person"), record(unit="percent"), record(period_type="M"))
    assert tables.parse_table(apart).ambiguous is False
    same = body(record(unit="person"), record(unit="person"), record(period="2021"))
    table = tables.parse_table(same)
    assert (table.ambiguous, table.duplicates) == (True, 2)


def test_a_category_without_an_id_is_told_apart_by_its_name():
    table = tables.parse_table(
        body(
            record(categories=(("Region", None, "Baku"),)),
            record(categories=(("Region", None, "Ganja"),)),
        )
    )
    assert table.ambiguous is False
    assert [row.categories for row in table.rows] == [("Baku",), ("Ganja",)]


def test_a_table_without_dimensions_or_rows_is_still_a_table():
    plain = tables.parse_table(body({"period": "2020", "value": 3, "period_type": "Y"}))
    assert (plain.dimensions, plain.rows[0].categories) == ((), ())
    assert tables.parse_table(body()).rows == ()


@pytest.mark.parametrize(
    "bad",
    [
        {"success": True, "data": []},
        {"success": True, "table": {"table_id": "X", "table_name": "Y"}, "data": {}},
        {"success": True, "table": {"table_name": "Y"}, "data": []},
        body({"value": 1}),
        body({"period": "2020"}),
        body(record(value="12")),
        body(record(value=True)),
        body(record(), record(categories=(("A", "1", "x"), ("B", "1", "y")))),
    ],
)
def test_an_answer_in_another_shape_fails_loudly(bad):
    with pytest.raises(UnexpectedShape):
        tables.parse_table(bad)


def test_period_limits_accept_numbers_and_text(population):
    rows = tables.select(population, period_from=2000, period_to="2005")
    assert {row.period for row in rows} == {"2000", "2001", "2002", "2003", "2004", "2005"}
    assert len(rows) == 6 * 5
    assert len(tables.select(population)) == 160
    assert tables.select(population, period_from="2030") == ()


def test_month_and_year_limits_on_monthly_rows(monthly):
    months = tables.select(monthly, period_from="2026-03", period_to="2026-05")
    assert {row.period for row in months} == {"202603", "202604", "202605"}
    assert len(tables.select(monthly, period_to="2026")) == len(monthly.rows)
    assert tables.select(monthly, period_from="2027") == ()


def test_a_category_filter_takes_a_dimension_name_part_of_it_or_its_number(civil_service):
    baku = [row for row in civil_service.rows if "baku" in row.categories[0].lower()]
    assert baku
    assert tables.select(civil_service, where={"1": "baku"}) == tuple(baku)
    assert tables.select(civil_service, where={"admin": "BAKU"}) == tuple(baku)
    full = "Administrative positions according to classifications"
    assert tables.select(civil_service, where={full: "baku"}) == tuple(baku)


def test_every_word_of_a_category_filter_must_appear_and_every_filter_must_match(civil_service):
    rows = tables.select(civil_service, where={"Indicator": "age under 25"})
    assert rows
    assert {row.categories[1] for row in rows} == {
        "by age structure from total number > under 25 years"
    }
    narrowed = tables.select(civil_service, where={"Indicator": "age under 25", "1": "baku"})
    assert 0 < len(narrowed) < len(rows)
    assert tables.select(civil_service, where={"Indicator": "no such category"}) == ()


def test_an_unknown_or_unclear_dimension_lists_the_real_ones(civil_service, teachers):
    with pytest.raises(
        tables.UnknownDimension, match=r"'nonsense'.*1\. Administrative.*2\. Indicator"
    ):
        tables.select(civil_service, where={"nonsense": "x"})
    with pytest.raises(tables.UnknownDimension, match=r"1\. Indicator; 2\. Indicator"):
        tables.select(teachers, where={"Indicator": "x"})
    assert tables.select(teachers, where={"2": "higher"})


def test_the_overview_counts_periods_units_and_categories(population):
    view = tables.overview(population)
    assert (view.rows, view.periods, view.first_period, view.last_period) == (
        160,
        32,
        "1995",
        "2026",
    )
    assert (view.period_types, view.units) == (("Y",), ("thsd.person",))
    [dimension] = view.dimensions
    assert (dimension.name, dimension.categories, dimension.matching) == ("Indicator", 5, 5)
    assert dimension.examples[0] == "Total population"


def test_the_overview_can_cap_and_search_categories(population):
    assert len(tables.overview(population, examples=2).dimensions[0].examples) == 2
    [dimension] = tables.overview(population, "URBAN").dimensions
    assert (dimension.categories, dimension.matching) == (5, 1)
    assert dimension.examples == ("Urban population",)
    assert tables.overview(population, "   ").dimensions[0].matching == 5


def test_the_overview_of_an_empty_table():
    view = tables.overview(tables.parse_table(body()))
    assert (view.rows, view.periods, view.first_period, view.last_period) == (0, 0, None, None)


def test_parsing_does_not_change_the_answer(load):
    answer = load("data_DT_AB_051.json")
    before = copy.deepcopy(answer)
    tables.parse_table(answer)
    assert answer == before
