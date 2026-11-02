import pytest

from azerbaijan_mcp_eqanun import acts
from azerbaijan_mcp_eqanun.errors import NotFound

EN_DASH, EM_DASH, NUMBER_SIGN = chr(0x2013), chr(0x2014), chr(0x2116)


@pytest.fixture(scope="module")
def code(raw):
    """Part of the Civil Code: articles 1, 2, 6, 13 and 14, the parts around them left out."""
    return acts.parse_act(raw("act_code.html"))


@pytest.fixture(scope="module")
def decree(raw):
    """A decision of the Ministry of Justice: numbered points, no articles."""
    return acts.parse_act(raw("act_decree.html"))


def test_the_charset_the_file_declares_is_used():
    assert acts.decode("<meta charset=utf-8>ə".encode()).endswith("ə")
    # the number sign is one byte, 0xb9, in windows-1251, the charset the files declare and the
    # one used when a file declares none or one this server does not know
    declared = b"<meta http-equiv=Content-Type content='text/html; charset=windows-1251'>\xb9"
    assert acts.decode(declared).endswith(NUMBER_SIGN)
    assert acts.decode(b"<meta charset=klingon>\xb9").endswith(NUMBER_SIGN)
    assert acts.decode(b"no charset at all \xb9").endswith(NUMBER_SIGN)


def test_a_real_file_is_split_into_articles_and_notes(code):
    assert [article.number for article in code.articles] == ["1", "2", "6", "13", "14"]
    assert code.articles[0].title.startswith("Azərbaycan Respublikası Mülki Məcəlləsinin məqsəd")
    assert sorted(code.notes) == [1, 2, 5, 7, 8]
    assert code.notes[2].startswith("20 oktyabr 2006-cı il 167-IIIQD nömrəli")
    # the number "[1]" the site writes in the title is a marker of the note, and the note's own
    # copy of it is not repeated in the note
    assert acts.visible(code.paragraphs[0]) == "AZƏRBAYCAN RESPUBLİKASININ MÜLKİ MƏCƏLLƏSİ[1]"
    assert not code.notes[1].startswith("[1]")


def test_an_article_comes_with_the_notes_its_text_points_to(code):
    view = acts.article_view(code, "1")
    assert view.heading.startswith("Maddə 1. Azərbaycan Respublikası Mülki Məcəlləsinin məqsəd")
    assert view.text.startswith("1.1. Bu Məcəllənin məqsədi üçüncü şəxslərin")
    assert "\n1.2. Bu Məcəllənin vəzifələri aşağıdakılardır:\n" in view.text
    assert [number for number, _ in view.notes] == [2]
    assert (view.previous, view.next) == (None, "2")
    assert acts.article_view(code, "6").notes[0][0] == 5


def test_a_note_in_the_heading_counts_even_when_word_wrapped_its_tag(code):
    # In the real file Word broke the anchor's style attribute right after "mso-endnote-id:".
    view = acts.article_view(code, "13")
    assert view.heading == "Maddə 13. Sahibkarlıq fəaliyyəti[7]"
    assert [number for number, _ in view.notes] == [7, 8]
    assert view.notes[0][1].startswith("24 iyun 2005-ci il 949-IIQD")


def test_a_chapter_line_ends_the_article_before_it(code):
    view = acts.article_view(code, "13")
    assert view.text.endswith("fəaliyyətdir.[8]")
    assert "fəsil" not in view.text
    assert "müdafiəsi" not in view.text
    assert acts.article_view(code, "14").previous == "13"
    assert acts.article_view(code, "14").next is None


def test_an_article_the_act_does_not_have_is_not_found(code):
    with pytest.raises(NotFound, match="no article 99"):
        acts.article_view(code, "99")


def test_an_act_without_articles_is_kept_as_paragraphs(decree):
    assert decree.articles == ()
    assert len(decree.paragraphs) == 21
    assert acts.visible(decree.paragraphs[2]) == "№ 17-N"
    assert acts.visible(decree.paragraphs[17]).endswith("istifadə qaydası [5]")
    assert sorted(decree.notes) == [1, 2, 3, 4, 5, 6, 10, 11]


def test_markers_of_notes_stay_in_the_text_as_square_brackets(code):
    assert "[1]" in code.text
    assert code.text.count("[") == sum(
        len(acts.TOKEN.findall(paragraph)) for paragraph in code.paragraphs
    )
    assert "⟦" not in code.text


@pytest.mark.parametrize(
    ("value", "number"),
    [
        ("105", "105"),
        (105, "105"),
        (" 7 ", "7"),
        ("Maddə 105", "105"),
        ("maddə 105-1.", "105-1"),
        ("Article 7", "7"),
        ("105 - 1", "105-1"),
        (f"105{EN_DASH}1", "105-1"),
        (f"938{EM_DASH}1", "938-1"),
        ("65-1-2", "65-1-2"),
    ],
)
def test_article_numbers_are_written_one_way(value, number):
    assert acts.normalize_article(value) == (number, None)


def test_a_part_of_an_article_names_the_article_and_says_so():
    assert acts.normalize_article("105.1-ci") == ("105", "105.1-ci is part 1 of article 105.")
    number, note = acts.normalize_article("6.1.2")
    assert number == "6"
    assert "part 1.2 of article 6" in note
    assert acts.normalize_article("65-1.2")[0] == "65-1"


@pytest.mark.parametrize("value", ["", "abc", "-5", "1--2", "Maddə", "1.a"])
def test_something_that_is_not_an_article_number_is_refused(value):
    with pytest.raises(ValueError, match="not an article number"):
        acts.normalize_article(value)


def test_dashes_in_a_number_are_read_whatever_their_kind(word):
    data = word(
        [
            "Maddə 938-1. Hyphen",
            "first",
            f"Maddə 938{EN_DASH}2. En dash",
            "second",
            f"Maddə 938 {EM_DASH} 3. Em dash and spaces",
            "third",
            "Maddə 939. Plain",
            "fourth",
        ]
    )
    assert [article.number for article in acts.parse_act(data).articles] == [
        "938-1",
        "938-2",
        "938-3",
        "939",
    ]


def test_headings_and_list_items_are_read_like_paragraphs(word):
    # Some codes set the title and the article heads as <h4>; the Tax Code has bulleted lists.
    data = word(
        [
            "<h4>AZƏRBAYCAN RESPUBLİKASININ CİNAYƏT MƏCƏLLƏSİ{1}",
            "<h4>Maddə 108-1. Məcburi hamiləlik {2}",
            "<li>first item{3}",
            "<li>second item",
            "Maddə 109. After the list",
            "closing text",
        ],
        {1: "note one", 2: "note two", 3: "note three"},
    )
    act = acts.parse_act(data)
    assert acts.visible(act.paragraphs[0]) == "AZƏRBAYCAN RESPUBLİKASININ CİNAYƏT MƏCƏLLƏSİ[1]"
    assert [article.number for article in act.articles] == ["108-1", "109"]
    view = acts.article_view(act, "108-1")
    assert view.heading == "Maddə 108-1. Məcburi hamiləlik [2]"
    assert view.text == "first item[3]\nsecond item"
    assert [number for number, _ in view.notes] == [2, 3]


@pytest.mark.parametrize("wrapped", [False, True])
def test_a_note_marker_is_found_whether_or_not_word_wrapped_its_tag(word, wrapped):
    data = word(
        ["Maddə 1. Title{1}", "Some text.{2}"],
        {1: "first note", 2: "second note\nwith two lines"},
        wrapped=wrapped,
    )
    act = acts.parse_act(data)
    assert acts.visible(act.paragraphs[0]) == "Maddə 1. Title[1]"
    notes = ((1, "first note"), (2, "second note\nwith two lines"))
    assert acts.article_view(act, "1").notes == notes


def test_an_act_with_no_list_of_notes_has_no_notes(word):
    act = acts.parse_act(word(["Maddə 1. Title", "Text."]))
    assert act.notes == {}
    assert acts.article_view(act, "1").notes == ()


def test_a_note_without_an_id_is_left_out():
    page = (
        b"<body><p>Text</p><div style='mso-element:endnote-list'>"
        b"<div style='mso-element:endnote'><p>no id</p></div>"
        b"<div style='mso-element:endnote' id=edn2><p>kept</p></div></div></body>"
    )
    assert acts.parse_act(page).notes == {2: "kept"}


def test_footnotes_are_read_like_endnotes():
    page = (
        "<body><p><a style='mso-footnote-id:ftn4' href='#_ftn4' name='_ftnref4'>[4]</a>"
        " Text</p><div style='mso-element:footnote-list'>"
        "<div style='mso-element:footnote' id=ftn4><p><a name='_ftn4'>[4]</a> The note</p></div>"
        "</div></body>"
    )
    act = acts.parse_act(page.encode())
    assert acts.visible(act.paragraphs[0]) == "[4] Text"
    assert act.notes == {4: "The note"}


def test_a_chapter_or_part_line_ends_an_article_in_any_wording(word):
    data = word(
        [
            "Maddə 1. First",
            "text of one",
            "ÜMUMİ HİSSƏ",
            "Maddə 2. Second",
            "text of two",
            "Birinci bölmə",
            "Maddə 3. Third",
            "text of three",
            "3-cü fəsil.",
            "Maddə 4. Fourth",
            "text of four",
            "Yekun müddəalar",
            "text of a closing clause",
        ]
    )
    act = acts.parse_act(data)
    texts = {a.number: acts.article_view(act, a.number).text for a in act.articles}
    assert texts == {
        "1": "text of one",
        "2": "text of two",
        "3": "text of three",
        "4": "text of four",
    }


def test_fold_ignores_case_and_accents():
    assert acts.fold("MƏHDUDLAŞDIRMA İşçi Iğdır") == "mehdudlasdirma isci igdir"


@pytest.mark.parametrize("text", ["№ 5 … ½ ™", "Straße ǰ ŉ", "İİ", "i\u0307", "plain"])
def test_fold_keeps_the_length_so_that_positions_agree(text):
    assert len(acts.fold(text)) == len(text)


def test_search_matches_without_accents_and_ranks_by_occurrences(code):
    total, matches = acts.search_act(code, "mulki", 10)
    assert total == 4
    assert [(m.article, m.hits) for m in matches] == [("1", 5), ("14", 5), ("2", 3), ("6", 2)]
    assert matches[0].heading.startswith("Maddə 1. Azərbaycan")
    assert "mülki" in matches[0].snippet.lower()


def test_a_final_k_or_q_in_the_query_is_ignored_so_that_word_forms_are_found(code):
    # "qanunvericilik" is written "qanunvericiliyi", "qanunvericiliyin" and so on in the text
    total, matches = acts.search_act(code, "mülki qanunvericilik", 10)
    assert total == 3
    assert {m.article for m in matches} == {"2", "6", "14"}


def test_all_words_must_be_in_the_same_article(code):
    assert acts.search_act(code, "sahibkarlıq hamiləlik", 10) == (0, [])
    total, matches = acts.search_act(code, "sahibkarliq", 10)
    assert (total, {m.article for m in matches}) == (2, {"1", "13"})


def test_a_result_says_where_it_starts_in_the_text(code, decree):
    for act in (code, decree):
        _, matches = acts.search_act(act, "məcəllə", 50)
        assert matches
        for match in matches:
            assert act.text[match.position :].startswith(match.heading[:30])


def test_results_can_be_paged(code):
    everything = acts.search_act(code, "mülki", 10)
    first = acts.search_act(code, "mülki", 2, 0)
    second = acts.search_act(code, "mülki", 2, 2)
    assert first[0] == second[0] == everything[0] == 4
    assert first[1] + second[1] == everything[1]
    assert acts.search_act(code, "mülki", 2, 4) == (4, [])


def test_in_an_act_without_articles_the_results_are_paragraphs(decree):
    total, matches = acts.search_act(decree, "qaydaları", 10)
    assert total == 4
    assert {m.article for m in matches} == {None}
    assert [m.position for m in matches] == sorted(m.position for m in matches)


def test_a_blank_query_finds_nothing(code):
    assert acts.search_act(code, "   ", 10) == (0, [])


def test_the_snippet_starts_near_the_first_word_even_after_long_symbols(word):
    # "№" and "…" grow when normalised in the compatibility way; positions must still agree
    lead = "№ … " * 200
    data = word(["Maddə 1. Title", lead + "the marker word sits here and runs on " + "x" * 300])
    act = acts.parse_act(data)
    _, matches = acts.search_act(act, "marker", 5)
    assert "marker word" in matches[0].snippet


def test_a_window_ends_at_a_line_break_when_one_is_near_the_end():
    text = "aaaa\nbbbb\ncccc\ndddd"
    assert acts.window(text, 0, 12) == ("aaaa\nbbbb", 10)
    assert acts.window(text, 10, 12) == ("cccc\ndddd", None)


def test_a_window_is_cut_hard_when_there_is_no_line_break_in_its_second_half():
    assert acts.window("x" * 100, 0, 40) == ("x" * 40, 40)
    assert acts.window("ab\n" + "c" * 50, 0, 40) == ("ab\n" + "c" * 37, 40)


def test_a_window_past_the_end_is_empty():
    assert acts.window("short", 0, 100) == ("short", None)
    assert acts.window("short", 10, 100) == ("", None)


def test_reading_window_by_window_reaches_every_line_whole():
    lines = [f"line number {n} with some words" for n in range(60)]
    text, offset, seen = "\n".join(lines), 0, []
    while offset is not None:
        piece, offset = acts.window(text, offset, 200)
        seen += piece.split("\n")
    assert seen == lines


@pytest.mark.parametrize(
    "tail",
    [
        ["Məcəlləyə əlavə və dəyişikliklər etmiş qanunlar:", "1. 26 may 2000-ci il tarixli"],
        ["Məcəlləyə əlavə və dəyişikliklər etmiş qanunlar", "1. 26 may 2000-ci il tarixli"],
        ["İSTİFADƏ OLUNMUŞ MƏNBƏ SƏNƏDLƏRİNİN SİYAHISI", "30 dekabr 1999-cu il tarixli"],
        ["ƏLAVƏLƏR", "1-ci əlavə"],
        ["İlham ƏLİYEV,", "Azərbaycan Respublikasının Prezidenti", "Bakı şəhəri", "№ 445-VIIQD"],
        ["Azərbaycan Respublikasının Prezidenti", "Bakı şəhəri, 13 iyul 2026-cı il"],
    ],
)
def test_what_follows_the_last_article_is_not_part_of_it(word, tail):
    # Without this the last article of a code took the lists of amending laws and of court
    # decisions that follow it: 74,000 characters after article 1325 of the Civil Code.
    act = acts.parse_act(
        word(["Maddə 1. First", "text of one", "Maddə 2. Last", "text of two", *tail])
    )
    assert acts.article_view(act, "2").text == "text of two"
    assert acts.article_view(act, "1").text == "text of one"
    assert act.text.endswith(acts.visible(tail[-1]))  # the tail is still in the act's text


@pytest.mark.parametrize(
    "line",
    [
        "Azərbaycan Respublikasının Prezidenti müəyyən edir.",
        "Azərbaycan Respublikasının Prezidenti:",  # the head of a list inside an article
        "Azərbaycan Respublikasının Prezidenti;",
        "Əlavələrin siyahısı bu Qanunun ayrılmaz hissəsidir.",
    ],
)
def test_a_line_that_only_looks_like_the_start_of_a_tail_does_not_end_an_article(word, line):
    act = acts.parse_act(word(["Maddə 1. First", line, "more"]))
    assert acts.article_view(act, "1").text == f"{line}\nmore"


def test_a_label_that_links_to_a_note_is_set_apart_from_the_word_before_it(word):
    act = acts.parse_act(word(["Maddə 373. İddia müddətləri<<#KM2>>", "373.1. Ten years."]))
    assert acts.article_view(act, "373").heading == "Maddə 373. İddia müddətləri KM2"
    assert act.articles[0].title == "İddia müddətləri KM2"


def test_links_to_other_acts_are_kept_with_their_labels_and_titles(word):
    act = acts.parse_act(
        word(
            [
                "Maddə 1. Limitation<<#KM2>>",
                "1.1. The general period is ten years. <<KMQ23|53598|Plenum decision of 2023>>",
                "1.2. Under the <<28 December 1999 law|1>> and again <<28 December 1999 law|1>>.",
                "Maddə 2. Next",
                "2.1. A link <<KMQ9|777>> without a title.",
            ]
        )
    )
    assert acts.article_view(act, "1").references == (
        acts.Reference("KMQ23", 53598, "Plenum decision of 2023"),
        acts.Reference("28 December 1999 law", 1, None),
    )
    assert acts.article_view(act, "2").references == (acts.Reference("KMQ9", 777, None),)


def test_links_are_found_whatever_their_scheme_host_or_attribute_order():
    page = (
        b"<body><p>See <a title='T &amp; U' target=_blank "
        b"href='http://www.e-qanun.az/framework/5#madde3'>the law</a>, "
        b'<a href="https://example.com/framework/6">another site</a>, '
        b'<a href="https://e-qanun.az/framework/7">ab</a> and '
        b'<a href="https://e-qanun.az/framework/8"><span>nested <b>label</b></span></a>.</p></body>'
    )
    act = acts.parse_act(page)
    assert act.links == (
        (acts.Reference("the law", 5, "T & U"), acts.Reference("nested label", 8, None)),
    )
    assert act.paragraphs == ("See the law, another site, ab and nested label.",)


def test_a_real_citation_keeps_the_title_the_site_gives_it(code, decree):
    assert [part for part in code.links if part] == [
        (acts.Reference("28 dekabr 1999-cu il tarixli 779-IQ nömrəli", 1, None),)
    ]
    cited = [link for part in decree.links for link in part]
    assert [(link.act_id, link.label) for link in cited] == [
        (41166, "2018-ci il 28 dekabr tarixli 455 nömrəli"),
        (53759, "2023-cü il 20 fevral tarixli 203s nömrəli"),
    ]
    assert cited[0].title == (
        "Azərbaycan Respublikası Prezidentinin 2018-ci il 28 dekabr tarixli 455 nömrəli Fərmanı"
    )


def test_the_links_of_a_stretch_of_text_are_found_by_where_it_lies(code):
    link = acts.Reference("28 dekabr 1999-cu il tarixli 779-IQ nömrəli", 1, None)
    second = code.starts[1]  # the paragraph that holds the link
    assert acts.references_between(code, 0, second) == ()
    assert acts.references_between(code, second, second + 5) == (link,)
    assert acts.references_between(code, second + 20, second + 30) == (link,)
    assert acts.references_between(code, code.starts[2], len(code.text)) == ()
    assert acts.references_between(code, 0, len(code.text)) == (link,)
