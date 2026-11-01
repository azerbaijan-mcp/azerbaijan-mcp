"""Release helpers for the monorepo.

    release.py resolve <tag>      print key=value lines for $GITHUB_OUTPUT
    release.py check [package..]  server.json and README agree with pyproject.toml
    release.py stamp <package>    copy the pyproject version into server.json

Tags look like <package>-v<version>, for example cbar-v0.1.0 or cbar-v0.1.0rc1.
"""

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG = re.compile(
    r"(?P<package>[a-z0-9]+(?:-[a-z0-9]+)*)"
    r"-v(?P<version>\d+\.\d+\.\d+(?:(?:a|b|rc)\d+|\.dev\d+)?)"
)
FINAL = re.compile(r"\d+\.\d+\.\d+")


class ReleaseError(Exception):
    """Something is wrong with the tag or the package metadata."""


def package_dir(package: str, root: Path = ROOT) -> Path:
    path = root / "packages" / package
    if not (path / "pyproject.toml").is_file():
        raise ReleaseError(f"no package at packages/{package}")
    return path


def read_project(path: Path) -> dict:
    with (path / "pyproject.toml").open("rb") as file:
        return tomllib.load(file)["project"]


def all_packages(root: Path = ROOT) -> list[str]:
    folders = (root / "packages").iterdir()
    return sorted(folder.name for folder in folders if (folder / "pyproject.toml").is_file())


def resolve(tag: str, root: Path = ROOT) -> dict[str, str]:
    """Map a release tag to the package it releases, checking that the version matches."""
    match = TAG.fullmatch(tag)
    if match is None:
        raise ReleaseError(f"tag {tag!r} is not <package>-v<version>, for example cbar-v0.1.0")
    package, version = match["package"], match["version"]
    project = read_project(package_dir(package, root))
    if project["version"] != version:
        raise ReleaseError(
            f"tag says {version} but packages/{package}/pyproject.toml says {project['version']}"
        )
    return {
        "package": package,
        "dist": project["name"],
        "version": version,
        "dir": f"packages/{package}",
        "prerelease": "false" if FINAL.fullmatch(version) else "true",
    }


def check(package: str, root: Path = ROOT) -> list[str]:
    """Problems with a package's registry metadata. An empty list means it is consistent."""
    path = package_dir(package, root)
    project = read_project(path)
    server_file = path / "server.json"
    if not server_file.is_file():
        return [f"{package}: server.json is missing"]
    server = json.loads(server_file.read_text(encoding="utf-8"))
    name, version = server.get("name", ""), project["version"]
    entry = (server.get("packages") or [{}])[0]
    problems = []
    if server.get("version") != version:
        problems.append(f"{package}: server.json version {server.get('version')} != {version}")
    if entry.get("registryType") != "pypi":
        problems.append(f"{package}: server.json packages[0].registryType must be pypi")
    if entry.get("identifier") != project["name"]:
        problems.append(f"{package}: server.json packages[0].identifier != {project['name']}")
    if entry.get("version") != version:
        problems.append(f"{package}: server.json packages[0].version != {version}")
    readme = (path / "README.md").read_text(encoding="utf-8")
    if f"mcp-name: {name}" not in readme:
        problems.append(f"{package}: README.md must contain 'mcp-name: {name}'")
    return problems


def stamp(package: str, root: Path = ROOT) -> None:
    """Copy the pyproject version into server.json, top level and first package entry."""
    path = package_dir(package, root)
    version = read_project(path)["version"]
    server_file = path / "server.json"
    server = json.loads(server_file.read_text(encoding="utf-8"))
    server["version"] = version
    for entry in server.get("packages", [])[:1]:
        entry["version"] = version
    text = json.dumps(server, indent=2, ensure_ascii=False) + "\n"
    server_file.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str]) -> int:
    command, args = (argv[0], argv[1:]) if argv else ("", [])
    if command == "resolve" and len(args) == 1:
        for key, value in resolve(args[0]).items():
            print(f"{key}={value}")
        return 0
    if command == "check":
        packages = args or all_packages()
        problems = [problem for package in packages for problem in check(package)]
        for problem in problems:
            print(problem, file=sys.stderr)
        if not problems:
            print("ok: " + ", ".join(packages))
        return 1 if problems else 0
    if command == "stamp" and len(args) == 1:
        stamp(args[0])
        print(f"stamped {args[0]}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
