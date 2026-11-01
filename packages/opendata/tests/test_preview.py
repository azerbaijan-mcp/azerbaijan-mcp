import pytest

from azerbaijan_mcp_opendata import preview


def test_decode_prefers_utf8_and_drops_the_bom():
    assert preview.decode("\ufeffAzərbaycan".encode()) == ("Azərbaycan", "utf-8")


def test_decode_falls_back_to_windows_1254():
    assert preview.decode("Şişli ığdır".encode("cp1254")) == ("Şişli ığdır", "cp1254")


def test_decode_last_resort_is_latin1():
    # 0xE9 is not UTF-8 here and 0x81 is undefined in Windows-1254.
    assert preview.decode(b"caf\xe9 \x81") == ("caf\xe9 \x81", "latin-1")


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ("a,b,c\n1,2,3\n4,5,6\n", ","),
        ("a;b;c\n1;2;3\n4;5;6\n", ";"),
        ("a\tb\tc\n1\t2\t3\n", "\t"),
        ("a|b|c\n1|2|3\n", "|"),
        ('a;b\n"1,5";"2,5"\n"3,5";"4,5"\n', ";"),
        ("one column\nof words\n", ","),
        ("", ","),
    ],
)
def test_sniff_delimiter(sample, expected):
    assert preview.sniff_delimiter(sample) == expected


def test_portal_style_csv_keeps_the_title_row_and_skips_blank_rows(read):
    out = preview.preview_csv(read("portal_style.csv"), rows=20)
    assert (out["encoding"], out["delimiter"]) == ("utf-8", ";")
    assert out["rows"][0][0] == "Example table title"
    assert out["rows"][1] == ["No", "Settlement\r\nname", "Area", "Population", "Note"]
    assert out["rows"][3] == ["2", "Beta", "8", "640", "has a; semicolon"]
    assert (out["total_rows"], out["blank_rows_skipped"], out["truncated"]) == (5, 1, False)


def test_csv_preview_is_capped_and_says_so(read):
    out = preview.preview_csv(read("portal_style.csv"), rows=2)
    assert len(out["rows"]) == 2
    assert (out["total_rows"], out["truncated"]) == (5, True)


def test_plain_csv_from_azstat(read):
    out = preview.preview_csv(read("azstat.csv"), rows=3)
    assert out["delimiter"] == ","
    assert out["rows"][0] == [
        "TIME_PERIOD",
        "DATASET_TITLE",
        "INDICATOR",
        "UNIT_MEASURE",
        "OBS_VALUE",
    ]
    assert out["total_rows"] == 12


def test_long_cells_are_clipped():
    out = preview.preview_csv(("a,b\n" + "x" * 500 + ",1\n").encode(), rows=5)
    cell = out["rows"][1][0]
    assert len(cell) == preview.MAX_CELL
    assert cell.endswith("…")


def test_a_cell_too_big_for_the_csv_parser_is_a_preview_error():
    with pytest.raises(preview.PreviewError, match="not readable as CSV"):
        preview.preview_csv(("a,b\n" + "x" * 200_000 + ",1\n").encode(), rows=5)


def test_json_table_is_found_under_a_key_and_the_rest_becomes_meta(read):
    out = preview.preview_json(read("azstat_data.json"), rows=2)
    assert out["table_key"] == "data"
    assert (out["total_records"], len(out["records"]), out["truncated"]) == (6, 2, True)
    assert out["records"][0]["level_1_name"] == "Total"
    assert out["records"][0]["value"] == 2078.7
    assert out["meta"]["count"] == 6
    assert "DT_BK_017" in out["meta"]["table"]


def test_the_largest_table_wins_and_nested_values_are_flattened():
    raw = b'{"small": [{"x": 1}], "big": [{"x": 1, "y": {"z": 2}}, {"x": 2}], "note": "n"}'
    out = preview.preview_json(raw, rows=10)
    assert out["table_key"] == "big"
    assert out["records"][0] == {"x": 1, "y": '{"z": 2}'}
    assert out["meta"] == {"small": '[{"x": 1}]', "note": "n"}
    assert out["truncated"] is False


def test_json_list_of_records_and_of_plain_values():
    records = preview.preview_json(b'[{"a": 1}, {"a": 2}]', rows=1)
    assert (records["table_key"], records["records"], records["total_records"]) == (
        None,
        [{"a": 1}],
        2,
    )
    assert records["meta"] is None
    values = preview.preview_json(b"[1, 2]", rows=5)
    assert values["records"] == [{"value": 1}, {"value": 2}]
    assert preview.preview_json(b"42", rows=5)["records"] == [{"value": 42}]


def test_json_without_a_table_has_no_records_but_keeps_meta():
    out = preview.preview_json(b'{"a": 1, "b": [1, 2]}', rows=5)
    assert (out["records"], out["total_records"], out["table_key"]) == ([], 0, None)
    assert out["meta"] == {"a": 1, "b": "[1, 2]"}


def test_json_with_a_bom_and_long_text():
    raw = b"\xef\xbb\xbf" + b'{"data": [{"text": "' + b"y" * 300 + b'"}]}'
    out = preview.preview_json(raw, rows=5)
    assert out["encoding"] == "utf-8"
    assert len(out["records"][0]["text"]) == preview.MAX_CELL


def test_invalid_json_is_a_preview_error():
    with pytest.raises(preview.PreviewError, match="not valid JSON"):
        preview.preview_json(b"<html>nope</html>", rows=5)


def test_json_nested_too_deeply_for_the_parser_is_a_preview_error():
    with pytest.raises(preview.PreviewError, match="nested too deeply"):
        preview.preview_json(b"[" * 100_000 + b"]" * 100_000, rows=5)


def test_json_nested_too_deeply_to_flatten_is_a_preview_error(monkeypatch):
    def too_deep(value):
        raise RecursionError

    monkeypatch.setattr(preview, "_small", too_deep)
    with pytest.raises(preview.PreviewError, match="nested too deeply"):
        preview.preview_json(b'{"data": [{"a": 1}]}', rows=5)
