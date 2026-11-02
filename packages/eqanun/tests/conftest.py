import html
import json
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from azerbaijan_mcp_eqanun.client import EqanunClient

FIXTURES = Path(__file__).parent / "fixtures"
API_HOST = "api.e-qanun.az"
FILES_HOST = "frameworks.e-qanun.az"
JSON = {"content-type": "application/json"}
ETAG = '"6adf0920-996c56"'
MODIFIED = "Mon, 26 Oct 2026 08:02:40 GMT"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}

# Act id -> the saved requisites. All are real answers. 46944 is the Civil Code, 41807 a repealed
# Cabinet decision and 42904 a decision of the Ministry of Justice, which has no articles.
FRAMEWORKS = {
    46944: "framework_code.json",
    41807: "framework_repealed.json",
    42904: "framework_decree.json",
}
VERSIONS = {46944: "versions_code.json", 42904: "versions_decree.json"}
# The act files are trimmed copies of real ones: some paragraphs and the notes they point to.
FILES = {"46/f_46944.html": "act_code.html", "42/f_42904.html": "act_decree.html"}


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_json(name: str) -> Any:
    return json.loads(fixture_bytes(name))


@dataclass
class Site:
    """A fake e-qanun.az that serves the saved answers and records every request.

    Set `override` to answer a request differently; return None to fall through.
    """

    override: Callable[[httpx.Request], httpx.Response | None] | None = None
    calls: list[httpx.Request] = field(default_factory=list)
    frameworks: dict[int, str] = field(default_factory=lambda: dict(FRAMEWORKS))
    files: dict[str, str] = field(default_factory=lambda: dict(FILES))
    etag: str = ETAG
    modified: str = MODIFIED

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.override is not None and (response := self.override(request)) is not None:
            return response
        if request.url.host == API_HOST:
            return self.api(request.url)
        if request.url.host == FILES_HOST:
            return self.file(request)
        return httpx.Response(404)

    def api(self, url: httpx.URL) -> httpx.Response:
        params = url.params
        path = url.path
        if path == "/getDetailSearch":
            if params.get("statusId") == "2":
                name = "search_repealed.json"
            elif params.get("text") == "true":
                name = "search_text.json"
            elif params.get("array") == "107":
                name = "search_type.json"
            else:
                name = "search_title.json"
            return httpx.Response(200, content=fixture_bytes(name), headers=JSON)
        if path == "/all-type":
            return httpx.Response(200, content=fixture_bytes("all_type.json"), headers=JSON)
        if path.startswith("/framework/"):
            ident = path.removeprefix("/framework/")
            if not ident.isdigit():
                return httpx.Response(400, json={"status": 400, "error": "Bad Request"})
            name = self.frameworks.get(int(ident))
            if name is None:
                return httpx.Response(500, json={"status": 500, "error": "Internal Server Error"})
            return httpx.Response(200, content=fixture_bytes(name), headers=JSON)
        if path == "/getVersions":
            name = VERSIONS.get(int(params.get("id", "0")))
            if name is None:
                return httpx.Response(200, json={"data": []})
            return httpx.Response(200, content=fixture_bytes(name), headers=JSON)
        return httpx.Response(404, json={"status": 404, "error": "Not Found"})

    def file(self, request: httpx.Request) -> httpx.Response:
        name = self.files.get(request.url.path.lstrip("/"))
        if name is None:
            return httpx.Response(404, text="Not Found")
        if request.headers.get("if-none-match") == self.etag:
            return httpx.Response(304, headers={"etag": self.etag})
        headers = {"content-type": "text/html", "etag": self.etag, "last-modified": self.modified}
        return httpx.Response(200, content=fixture_bytes(name), headers=headers)

    @property
    def http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def api_calls(self, path: str | None = None) -> list[httpx.URL]:
        urls = [call.url for call in self.calls if call.url.host == API_HOST]
        return [url for url in urls if path is None or url.path == path]

    def file_calls(self) -> list[httpx.URL]:
        return [call.url for call in self.calls if call.url.host == FILES_HOST]


@pytest.fixture(autouse=True)
def no_network(request):
    """Offline tests never reach the real site: outside connections fail at once.

    Loopback stays open because asyncio itself connects a pair of local sockets on Windows.
    """
    if request.node.get_closest_marker("live"):
        yield
        return
    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def host(address) -> str:
        return address[0] if isinstance(address, tuple) else str(address)

    def connect(self, address):
        if host(address) not in LOCAL_HOSTS:
            raise RuntimeError(f"network access is blocked in these tests: {host(address)}")
        return real_connect(self, address)

    def getaddrinfo(name, *args, **kwargs):
        if name is not None and name not in LOCAL_HOSTS:
            raise RuntimeError(f"network access is blocked in these tests: {name}")
        return real_getaddrinfo(name, *args, **kwargs)

    patch = pytest.MonkeyPatch()
    patch.setattr(socket.socket, "connect", connect)
    patch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield
    patch.undo()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def load() -> Callable[[str], Any]:
    """A saved JSON answer, parsed."""
    return fixture_json


@pytest.fixture(scope="session")
def raw() -> Callable[[str], bytes]:
    """A saved act file, as the site serves it."""
    return fixture_bytes


@pytest.fixture
def site() -> Site:
    return Site()


@pytest.fixture
def client(site: Site) -> EqanunClient:
    return EqanunClient(http=site.http, min_interval=0, retry_delay=0)


@pytest.fixture(scope="session")
def word() -> Callable[..., bytes]:
    """Build an act file the way Word exports it, from paragraphs of text.

    `{7}` in a paragraph puts the anchor of endnote 7 there. `<<label|53598|title>>` puts a link
    to act 53598 there, with a title if one is given, and `<<#KM2>>` a label that links to a
    note in the file. A paragraph that starts with `<h4>` or `<li>` is that element instead of a
    <p>. With `wrapped`, the anchor's style attribute breaks after its colon, as Word does at the
    end of a long line.
    """

    def anchor(number: int, wrapped: bool) -> str:
        gap = "\n" if wrapped else ""
        return (
            f"<a style='mso-endnote-id:{gap}edn{number}' href=\"#_edn{number}\" "
            f'name="_ednref{number}" title=""><span class=MsoEndnoteReference>'
            f"<![if !supportFootnotes]><span class=MsoEndnoteReference>[{number}]</span>"
            "<![endif]></span></a>"
        )

    def link(spec: str) -> str:
        if spec.startswith("#"):
            return f'<a href="{spec}"><b><sup><span lang=AZ-LATIN>{spec[1:]}</span></sup></b></a>'
        label, number, *title = spec.split("|")
        said = f' title="{html.escape(title[0])}"' if title else ""
        return (
            f'<a href="https://e-qanun.az/framework/{number}" target="_blank"{said}>'
            f"<b><span lang=AZ-LATIN>{html.escape(label)}</span></b></a>"
        )

    def build(
        paragraphs: list[str], notes: dict[int, str] | None = None, *, wrapped: bool = False
    ) -> bytes:
        body = []
        for paragraph in paragraphs:
            tag = "p"
            if paragraph[:4] in ("<h4>", "<li>"):  # headings and list items, as some codes have
                tag, paragraph = paragraph[1:3], paragraph[4:]
            parts = []
            for piece in re.split(
                r"(\{\d+\}|&lt;&lt;.*?&gt;&gt;)", html.escape(paragraph, quote=False)
            ):
                if re.fullmatch(r"\{\d+\}", piece):
                    parts.append(anchor(int(piece[1:-1]), wrapped))
                elif piece.startswith("&lt;&lt;"):
                    parts.append(link(html.unescape(piece[8:-8])))
                else:
                    parts.append(piece)
            body.append(
                f"<{tag} class=MsoNormal><span lang=AZ-LATIN>{''.join(parts)}</span></{tag}>"
            )
        listed = ""
        if notes is not None:
            items = []
            for number, text in notes.items():
                first, *more = (html.escape(line, quote=False) for line in text.split("\n"))
                items.append(
                    f"<div style='mso-element:endnote' id=edn{number}>"
                    f"<p class=MsoEndnoteText><a style='mso-endnote-id:edn{number}' "
                    f'href="#_ednref{number}" name="_edn{number}" title="">[{number}]</a>'
                    f"<span> {first}</span></p>"
                    + "".join(f"<p class=MsoEndnoteText><span>{line}</span></p>" for line in more)
                    + "</div>"
                )
            listed = (
                "<div style='mso-element:endnote-list'><![if !supportEndnotes]><br clear=all>"
                "<![endif]>" + "".join(items) + "</div>"
            )
        document = (
            '<html><head><meta http-equiv=Content-Type content="text/html; charset=windows-1251">'
            "<title>Act</title></head><body lang=RU><div class=WordSection1>"
            + "\n\n".join(body)
            + "</div>"
            + listed
            + "</body></html>"
        )
        return document.encode("windows-1251", errors="xmlcharrefreplace")

    return build
