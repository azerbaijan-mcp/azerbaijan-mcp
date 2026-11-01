import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)


def make_package(
    root: Path,
    *,
    version: str = "1.2.3",
    server_version: str = "1.2.3",
    marker: bool = True,
    identifier: str = "azerbaijan-mcp-demo",
    registry_type: str = "pypi",
    server: bool = True,
) -> Path:
    package = root / "packages" / "demo"
    package.mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        f'[project]\nname = "azerbaijan-mcp-demo"\nversion = "{version}"\n', encoding="utf-8"
    )
    readme = "# demo\n"
    if marker:
        readme = "<!-- mcp-name: io.github.azerbaijan-mcp/demo -->\n\n" + readme
    (package / "README.md").write_text(readme, encoding="utf-8")
    if server:
        document = {
            "name": "io.github.azerbaijan-mcp/demo",
            "version": server_version,
            "packages": [
                {"registryType": registry_type, "identifier": identifier, "version": server_version}
            ],
        }
        (package / "server.json").write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8"
        )
    return package


def test_resolve_final_release(tmp_path):
    make_package(tmp_path)
    assert release.resolve("demo-v1.2.3", tmp_path) == {
        "package": "demo",
        "dist": "azerbaijan-mcp-demo",
        "version": "1.2.3",
        "dir": "packages/demo",
        "prerelease": "false",
    }


def test_resolve_prerelease(tmp_path):
    make_package(tmp_path, version="1.2.3rc1", server_version="1.2.3rc1")
    assert release.resolve("demo-v1.2.3rc1", tmp_path)["prerelease"] == "true"


@pytest.mark.parametrize(
    "tag",
    ["v1.2.3", "demo-1.2.3", "demo-v1.2", "Demo-v1.2.3", "demo-v1.2.3-beta", "demo-v1.2.3\n"],
)
def test_resolve_rejects_malformed_tags(tmp_path, tag):
    make_package(tmp_path)
    with pytest.raises(release.ReleaseError, match="not <package>-v<version>"):
        release.resolve(tag, tmp_path)


def test_resolve_rejects_a_version_mismatch(tmp_path):
    make_package(tmp_path, version="1.2.4", server_version="1.2.4")
    with pytest.raises(release.ReleaseError, match=r"1\.2\.4"):
        release.resolve("demo-v1.2.3", tmp_path)


def test_resolve_rejects_an_unknown_package(tmp_path):
    make_package(tmp_path)
    with pytest.raises(release.ReleaseError, match="no package at packages/nope"):
        release.resolve("nope-v1.2.3", tmp_path)


def test_check_accepts_consistent_metadata(tmp_path):
    make_package(tmp_path)
    assert release.check("demo", tmp_path) == []


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({"server_version": "9.9.9"}, "version 9.9.9"),
        ({"marker": False}, "mcp-name"),
        ({"identifier": "other"}, "identifier"),
        ({"registry_type": "npm"}, "registryType"),
        ({"server": False}, "server.json is missing"),
    ],
)
def test_check_reports_problems(tmp_path, options, expected):
    make_package(tmp_path, **options)
    problems = release.check("demo", tmp_path)
    assert any(expected in problem for problem in problems)


def test_stamp_copies_the_version_and_is_idempotent(tmp_path):
    package = make_package(tmp_path, version="2.0.0", server_version="1.2.3")
    release.stamp("demo", tmp_path)
    document = json.loads((package / "server.json").read_text(encoding="utf-8"))
    assert document["version"] == "2.0.0"
    assert document["packages"][0]["version"] == "2.0.0"
    once = (package / "server.json").read_bytes()
    release.stamp("demo", tmp_path)
    assert (package / "server.json").read_bytes() == once


def test_every_real_package_is_consistent():
    for package in release.all_packages():
        assert release.check(package) == [], package


def test_committed_server_json_files_use_the_format_stamp_writes():
    for package in release.all_packages():
        text = (ROOT / "packages" / package / "server.json").read_text(encoding="utf-8")
        assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n", package


def test_main_check_passes_on_the_repo(capsys):
    assert release.main(["check"]) == 0
    assert capsys.readouterr().out.startswith("ok:")


def test_main_without_arguments_prints_usage(capsys):
    assert release.main([]) == 2
    assert "release.py resolve" in capsys.readouterr().err
