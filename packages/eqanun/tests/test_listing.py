import pytest

from azerbaijan_mcp_eqanun import listing
from azerbaijan_mcp_eqanun.errors import UnexpectedShape


@pytest.fixture(scope="module")
def types(load):
    return listing.parse_types(load("all_type.json"))


def test_a_search_answer_becomes_acts_with_dates_in_iso_form(load):
    total, acts = listing.parse_search(load("search_title.json"))
    assert (total, len(acts)) == (633, 3)
    court, committee, cabinet = acts
    assert court == listing.ActSummary(
        id=62704,
        title=court.title,
        type="KONSTİTUSİYA MƏHKƏMƏSİNİN QƏRARLARI",
        status="in_force",
        status_text="Qüvvədədir",
        accept_date="2026-09-21",
        effect_date=None,
        register_code="21202609210249",
        citation=None,
    )
    assert court.title.startswith("Azərbaycan Respublikası Konstitusiyasının 61 və 71-ci maddələri")
    assert (committee.id, committee.type, committee.citation) == (
        62709,
        "Dövlət Statistika Komitəsi",
        "3-34/3-2-22/2026",
    )
    assert (cabinet.id, cabinet.citation, cabinet.accept_date) == (62679, "674s", "2026-09-10")


def test_repealed_acts_are_marked_and_keep_the_sites_wording(load):
    total, acts = listing.parse_search(load("search_repealed.json"))
    assert total == 13
    assert [(act.id, act.status, act.status_text) for act in acts] == [
        (41807, "repealed", "Ləğv olunmuşdur"),
        (3097, "repealed", "Ləğv olunmuşdur"),
    ]


def test_an_acts_requisites_are_read(load):
    meta = listing.parse_framework(load("framework_code.json"))
    assert meta.summary.id == 46944
    assert meta.summary.title == "Azərbaycan Respublikasının Mülki Məcəlləsi"
    assert meta.summary.type == "Məcəllələr"
    assert (meta.summary.accept_date, meta.summary.effect_date) == ("1999-12-28", "2000-09-01")
    assert meta.summary.citation is None
    assert meta.class_codes == ("020.010.000",)
    assert meta.register_date is None
    assert meta.publications == ()
    assert meta.html_url == "https://e-qanun.az/frameworks/46/f_46944.html"


def test_publications_are_grouped_by_where_the_act_appeared(load):
    meta = listing.parse_framework(load("framework_repealed.json"))
    assert meta.summary.status == "repealed"
    assert meta.summary.citation == "107"
    assert meta.register_date == "2019-03-29"
    assert [p.source for p in meta.publications] == [
        "Xalq Qəzeti",
        "Azərbaycan Respublikasının Qanunvericilik Toplusu",
    ]
    assert meta.publications[0].details == (
        ("Dərc olunma tarixi", "20-03-2019"),
        ("Nəşr Nömrəsi", "64"),
    )
    assert len(meta.publications[1].details) == 3


def test_editions_come_with_their_dates_and_files(load):
    versions = listing.parse_versions(load("versions_code.json"))
    assert [(v.id, v.effective_date, v.file) for v in versions] == [
        (20133, "2026-07-14", "46/v_46944_19.html"),
        (19927, "2026-05-26", "46/v_46944_18.html"),
        (19677, "2026-02-27", "46/v_46944_17.html"),
    ]
    assert listing.parse_versions({"data": []}) == ()


def test_the_type_tree_loses_the_counts_the_site_adds_to_names(types):
    assert len(types) == 81
    by_id = {node.id: node for node in types}
    assert by_id[25] == listing.TypeNode(
        25, "AZƏRBAYCAN RESPUBLİKASININ KONSTİTUSİYASI VƏ REFERENDUM AKTLARI", None
    )
    assert by_id[107] == listing.TypeNode(107, "Məcəllələr", 29)
    assert not any(node.name.endswith(")") for node in types)


@pytest.mark.parametrize(
    ("words", "ids"),
    [
        ("məcəllə", {107}),
        ("mecelle", {107}),
        ("qanun", {28, 30, 107}),  # the group of laws stands for its parts, codes among them
        ("fərman", {31}),
        ("sərəncam", {84, 85}),
        ("nazirlər kabineti", {32, 85}),
        ("Maliyyə Nazirliyi", {44}),
    ],
)
def test_a_kind_of_act_is_found_by_words_from_its_name(types, words, ids):
    assert {node.id for node in listing.resolve_types(types, words)} == ids


@pytest.mark.parametrize("words", ["xyz", "", "   ", "məcəllə xyz"])
def test_words_that_match_no_kind_give_none(types, words):
    assert listing.resolve_types(types, words) == []


def test_a_group_is_never_returned_itself_because_the_site_finds_nothing_under_it(types):
    parents = {node.parent_id for node in types if node.parent_id is not None}
    assert all(node.id not in parents for node in listing.resolve_types(types, "qanun"))


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("03.09.2026", "2026-09-03"),
        (" 28.12.1999 ", "1999-12-28"),
        ("31.02.2026", None),
        ("2026-09-03", None),
        ("None", None),
        ("", None),
        (None, None),
    ],
)
def test_dates_are_turned_into_iso_form_or_dropped(text, iso):
    assert listing.iso_date(text) == iso


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("Qüvvədədir", "in_force"),
        ("QÜVVƏDƏDİR", "in_force"),
        ("Ləğv olunmuşdur", "repealed"),
        ("Qüvvəsini itirmişdir", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_the_status_is_what_the_site_says_or_unknown(text, status):
    assert listing.status_of(text) == status


@pytest.mark.parametrize(
    "url",
    [
        "https://e-qanun.az/frameworks/46/f_46944.html",
        "https://frameworks.e-qanun.az/46/f_46944.html",
    ],
)
def test_an_act_file_may_be_on_the_main_host_or_the_files_host(url):
    assert listing.file_path(url) == "46/f_46944.html"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/frameworks/46/f_46944.html",
        "http://e-qanun.az/frameworks/46/f_46944.html",
        "https://e-qanun.az.evil.example/frameworks/46/f_46944.html",
        "https://e-qanun.az/frameworks/../f_46944.html",
        "https://e-qanun.az/frameworks/46/f_46944.html?x=1",
        "https://e-qanun.az/frameworks/46/f_46944.pdf",
        "https://e-qanun.az/other/46/f_46944.html",
        "file:///etc/passwd",
        "",
    ],
)
def test_an_address_off_the_site_is_not_followed(url):
    with pytest.raises(UnexpectedShape):
        listing.file_path(url)


@pytest.mark.parametrize(
    ("parse", "body"),
    [
        (listing.parse_search, {"data": None}),
        (listing.parse_search, []),
        (listing.parse_search, {"data": [{"title": "no id"}]}),
        (listing.parse_search, {"data": [], "totalCount": "many"}),
        (listing.parse_framework, {}),
        (listing.parse_framework, {"data": {"requisite": {"title": "x"}}}),
        (
            listing.parse_framework,
            {"data": {"requisite": {"title": "x"}, "htmlUrl": "u", "id": "a"}},
        ),
        (listing.parse_versions, []),
        (listing.parse_versions, {"data": [{"effectDate": "01.01.2026"}]}),
        (listing.parse_types, {"data": [{"id": "x", "name": "n"}]}),
        (listing.parse_types, "nothing"),
    ],
)
def test_an_answer_of_another_shape_is_reported_not_guessed_at(parse, body):
    with pytest.raises(UnexpectedShape):
        parse(body)
