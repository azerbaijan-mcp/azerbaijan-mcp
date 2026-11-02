"""Read an act's file: the text, the articles and the amendment notes.

The act files on e-qanun.az are Word-exported HTML. They declare windows-1251, write the Azerbaijani
letters outside it as numeric entities (&#601; for ə), mark amendment notes as Word endnotes
(`mso-endnote-id:ednN` in the text, `<div style='mso-element:endnote' id=ednN>` in a list at the
end) and head an article with a paragraph that starts with "Maddə N.". This module turns such a
file into paragraphs, articles, notes and the links to other acts. It does no network access.
"""

import bisect
import codecs
import html
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .errors import NotFound

FOLD = str.maketrans({"ı": "i", "ə": "e"})
META_CHARSET = re.compile(rb"charset=[\"']?([A-Za-z0-9_\-]+)", re.I)
# A paragraph is a <p>, a heading or a list item: some codes set the title and the article heads
# as <h4>, and the Tax Code has bulleted lists whose items are <li> with no <p> inside.
PARAGRAPH = re.compile(r"(?is)<(p|h[1-6]|li)\b[^>]*>(.*?)</\1\s*>")
CONDITIONAL = re.compile(r"(?s)<!\[if[^\]]*\]>|<!\[endif\]>|<!--.*?-->")
TAG = re.compile(r"(?s)<[^>]+>")
# Word breaks lines anywhere in a tag, even right after the colon in `mso-endnote-id:` + `edn7`.
NOTE_REFERENCE = re.compile(
    r"(?is)<a\b[^>]*?mso-(?:end|foot)note-id\s*:\s*(?:edn|ftn)(\d+)[^>]*?"
    r"name\s*=\s*[\"']?_(?:edn|ftn)ref\d+[\"']?[^>]*>.*?</a>"
)
NOTE_OPEN = re.compile(r"(?is)<div\b[^>]*mso-element\s*:\s*(?:end|foot)note(?![-\w])[^>]*>")
NOTE_ID = re.compile(r"(?i)\bid\s*=\s*[\"']?(?:edn|ftn)(\d+)")
NOTE_LIST = re.compile(r"(?i)mso-element\s*:\s*(?:end|foot)note-list")
TOKEN = re.compile(r"⟦(\d+)⟧")
DASH = "-" + chr(0x2013) + chr(0x2014)  # hyphen, en dash, em dash: all three occur in "938-1"
ARTICLE = re.compile(rf"^Maddə\s+(\d+(?:\s*[{DASH}]\s*\d+)*)\s*[.:]?\s*(.*)$", re.I)
DASHES = re.compile(rf"\s*[{DASH}]\s*")
# Chapter and part lines, as fold() writes them: "1-ci fəsil.", "Birinci bölmə", "ÜMUMİ HİSSƏ".
ORDINAL = r"(?:\d+|[ivxlc]+)(?:-?(?:ci|cu|inci|uncu))?"
WORD_ORDINAL = (
    r"(?:birinci|ikinci|ucuncu|dorduncu|besinci|altinci|yeddinci|sekkizinci|doqquzuncu|onuncu)"
)
STRUCTURE = re.compile(
    rf"^(?:{ORDINAL}\s+(?:fesil|bolme|hisse|paraqraf)|{WORD_ORDINAL}\s+(?:fesil|bolme|hisse)"
    r"|(?:umumi|xususi|yekun|kecid)\s+(?:hisse|muddealar))\.?$"
)
# What follows the last article and is not part of it: the list of amending laws, the list of
# sources, the annexes and the President's signature ("Azərbaycan Respublikasının Prezidenti").
TAIL = re.compile(
    r"^(?:(?:\w+\s+)?elave\s+ve\s+deyisiklikler\s+etmis\s+(?:qanunlar|aktlar)\s*:?"
    r"|istifade\s+olunmus\s+menbe\s+senedlerinin\s+siyahisi|elaveler"
    r"|azerbaycan\s+respublikasinin\s+prezidenti)$"
)
SIGNED_BY_NAME = 40  # a line this short, ending in a comma, before the title is the name
ANCHOR = re.compile(r"(?is)<a\b([^>]*)>(.*?)</a>")
ACT_LINK = re.compile(r"(?i)\bhref\s*=\s*[\"']?https?://(?:www\.)?e-qanun\.az/framework/(\d+)")
TITLE_ATTRIBUTE = re.compile(r"(?is)\btitle\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
MIN_LABEL = 3
# The Civil Code marks a few passages with a label such as KM2 that links to a note in the file;
# Word sets it right against the word before, as in "müddətləriKM2".
LOCAL_LABEL = re.compile(r"(?is)<a\b[^>]*\bhref\s*=\s*[\"']#KM\d+[\"']")
SNIPPET_CHARS = 240


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.casefold().translate(FOLD))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def fold(text: str) -> str:
    """Lower-case and strip accents, so that "mehdudlasdirma" finds "məhdudlaşdırma".

    The result is as long as the text, so a position found in one is a position in the other.
    """
    folded = _fold(text)
    if len(folded) == len(text):
        return folded
    return "".join((_fold(char) or char)[0] for char in text)


@dataclass(frozen=True, slots=True)
class Article:
    number: str
    title: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Reference:
    """Words of the text that link to another act on e-qanun.az, such as KMQ23 or a citation."""

    label: str
    act_id: int
    title: str | None


@dataclass(frozen=True, slots=True)
class ParsedAct:
    paragraphs: tuple[str, ...]
    notes: dict[int, str]
    articles: tuple[Article, ...]
    text: str
    starts: tuple[int, ...]
    links: tuple[tuple[Reference, ...], ...]
    memo: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class ArticleView:
    number: str
    heading: str
    text: str
    notes: tuple[tuple[int, str], ...]
    references: tuple[Reference, ...]
    previous: str | None
    next: str | None


@dataclass(frozen=True, slots=True)
class Match:
    article: str | None
    heading: str
    hits: int
    snippet: str
    position: int


@dataclass(frozen=True, slots=True)
class Segment:
    number: str | None
    heading: str
    shown: str
    folded: str
    position: int


def decode(raw: bytes) -> str:
    """Decode with the charset the file declares, windows-1251 when it declares none we know."""
    found = META_CHARSET.search(raw[:4096])
    name = found.group(1).decode("ascii", "ignore") if found else "windows-1251"
    try:
        codecs.lookup(name)
    except LookupError:
        name = "windows-1251"
    return raw.decode(name, errors="replace")


def _plain(fragment: str) -> str:
    text = html.unescape(TAG.sub("", CONDITIONAL.sub("", fragment)))
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _paragraph(fragment: str) -> str:
    spaced = LOCAL_LABEL.sub(lambda found: " " + found.group(0), CONDITIONAL.sub("", fragment))
    return _plain(NOTE_REFERENCE.sub(lambda found: f"⟦{found.group(1)}⟧", spaced))


def _references(fragment: str) -> tuple[Reference, ...]:
    """The links to other acts on e-qanun.az in a paragraph, once each."""
    found: dict[Reference, None] = {}
    for anchor in ANCHOR.finditer(fragment):
        link = ACT_LINK.search(anchor.group(1))
        label = _plain(anchor.group(2)) if link else ""
        if not link or len(label) < MIN_LABEL:
            continue
        said = TITLE_ATTRIBUTE.search(anchor.group(1))
        title = None
        if said:
            given = next(group for group in said.groups() if group is not None)
            title = " ".join(html.unescape(given).split()) or None
        found[Reference(label, int(link.group(1)), title)] = None
    return tuple(found)


def _notes(region: str) -> dict[int, str]:
    notes: dict[int, str] = {}
    for opening in NOTE_OPEN.finditer(region):
        found = NOTE_ID.search(opening.group(0))
        if not found:
            continue
        end = region.find("</div>", opening.end())
        inner = region[opening.end() : end if end >= 0 else len(region)]
        lines = [_plain(block.group(2)) for block in PARAGRAPH.finditer(inner)]
        lines = [line for line in lines if line]
        if lines:
            lines[0] = re.sub(r"^\[\d+\]\s*", "", lines[0])
            notes[int(found.group(1))] = "\n".join(line for line in lines if line)
    return notes


def _articles(paragraphs: list[str]) -> tuple[Article, ...]:
    """Heads of articles, each running to the next head, chapter or part line, or the tail."""
    heads: list[tuple[str, str, int]] = []
    ends: list[int] = []
    for index, paragraph in enumerate(paragraphs):
        bare = TOKEN.sub("", paragraph).strip()
        found = ARTICLE.match(bare)
        if found:
            heads.append((DASHES.sub("-", found.group(1)), found.group(2).strip(), index))
            continue
        folded = fold(bare)
        if STRUCTURE.match(folded):
            ends.append(index)
        elif TAIL.match(folded):
            before = paragraphs[index - 1].rstrip() if index else ""
            signed = folded.endswith("prezidenti") and before.endswith(",")
            ends.append(index - 1 if signed and len(before) <= SIGNED_BY_NAME else index)
    articles = []
    for position, (number, title, start) in enumerate(heads):
        limit = heads[position + 1][2] if position + 1 < len(heads) else len(paragraphs)
        end = min([limit, *(mark for mark in ends if start < mark < limit)])
        articles.append(Article(number, title, start, end))
    return tuple(articles)


def parse_act(raw: bytes) -> ParsedAct:
    text = decode(raw)
    start = text.find("<body")
    start = text.find(">", start) + 1 if start >= 0 else 0
    stop = text.rfind("</body>")
    body = text[start : stop if stop > start else len(text)]
    listed = NOTE_LIST.search(body)
    main, region = (body[: listed.start()], body[listed.start() :]) if listed else (body, "")
    paragraphs: list[str] = []
    links: list[tuple[Reference, ...]] = []
    for block in PARAGRAPH.finditer(main):
        paragraph = _paragraph(block.group(2))
        if paragraph:
            paragraphs.append(paragraph)
            links.append(_references(block.group(2)))
    shown = [visible(paragraph) for paragraph in paragraphs]
    starts, position = [], 0
    for line in shown:
        starts.append(position)
        position += len(line) + 1
    return ParsedAct(
        paragraphs=tuple(paragraphs),
        notes=_notes(region),
        articles=_articles(paragraphs),
        text="\n".join(shown),
        starts=tuple(starts),
        links=tuple(links),
    )


def visible(paragraph: str) -> str:
    """A paragraph as the site shows it: an amendment note marker reads [12]."""
    return TOKEN.sub(lambda found: f"[{found.group(1)}]", paragraph)


def normalize_article(value: str | int) -> tuple[str, str | None]:
    """The article number, and a note when the text named a part of an article (105.1)."""
    text = re.sub(r"(?i)^(?:maddə|madde|article)\s*", "", str(value).strip())
    text = DASHES.sub("-", text.strip().rstrip(".").strip())
    if re.fullmatch(r"\d+(?:-\d+)*", text):
        return text, None
    part = re.fullmatch(r"(\d+(?:-\d+)*)\.(\d+(?:\.\d+)*)(?:-?(?:ci|cı|cu|cü))?", text, re.I)
    if part:
        return part.group(1), f"{value!s} is part {part.group(2)} of article {part.group(1)}."
    raise ValueError(f"{value!r} is not an article number such as 105 or 105-1.")


def article_view(act: ParsedAct, number: str) -> ArticleView:
    position = next((i for i, item in enumerate(act.articles) if item.number == number), None)
    if position is None:
        raise NotFound(f"The act has no article {number}.")
    article = act.articles[position]
    paragraphs = act.paragraphs[article.start : article.end]
    numbers = [int(found.group(1)) for part in paragraphs for found in TOKEN.finditer(part)]
    notes = tuple((n, act.notes[n]) for n in dict.fromkeys(numbers) if n in act.notes)
    references = dict.fromkeys(
        link for part in act.links[article.start : article.end] for link in part
    )
    before = act.articles[position - 1].number if position else None
    after = act.articles[position + 1].number if position + 1 < len(act.articles) else None
    return ArticleView(
        number=number,
        heading=visible(paragraphs[0]),
        text="\n".join(visible(part) for part in paragraphs[1:]),
        notes=notes,
        references=tuple(references),
        previous=before,
        next=after,
    )


def references_between(act: ParsedAct, begin: int, end: int) -> tuple[Reference, ...]:
    """The links in the paragraphs that overlap characters `begin` to `end` of `act.text`."""
    first = max(bisect.bisect_right(act.starts, begin) - 1, 0)
    last = bisect.bisect_left(act.starts, end)
    return tuple(dict.fromkeys(link for part in act.links[first:last] for link in part))


def _segments(act: ParsedAct) -> list[Segment]:
    """The parts a search looks in, each with its text folded once: articles, else paragraphs."""
    if "segments" not in act.memo:
        if act.articles:
            spans = [(a.number, a.start, a.end) for a in act.articles]
        else:
            spans = [(None, index, index + 1) for index in range(len(act.paragraphs))]
        segments = []
        for number, start, end in spans:
            parts = [visible(part) for part in act.paragraphs[start:end]]
            shown = "\n".join(parts)
            segments.append(Segment(number, parts[0], shown, fold(shown), act.starts[start]))
        act.memo["segments"] = segments
    return act.memo["segments"]


def _stem(word: str) -> str:
    """Without a final k or q, which becomes y or ğ before a suffix: qanunvericiliyi."""
    return word[:-1] if len(word) > 4 and word[-1] in "kq" else word


def search_act(act: ParsedAct, query: str, limit: int, offset: int = 0) -> tuple[int, list[Match]]:
    """Articles (or paragraphs, in an act without articles) that contain every word of the query.

    A word matches as part of a longer word and without accents. Those with the most occurrences
    come first. `position` is where the part starts in `act.text`.
    """
    words = [_stem(word) for word in fold(query).split()]
    if not words:
        return 0, []
    found: list[tuple[int, int, Match]] = []
    for order, segment in enumerate(_segments(act)):
        if not all(word in segment.folded for word in words):
            continue
        hits = sum(segment.folded.count(word) for word in words)
        begin = max(0, segment.folded.find(words[0]) - SNIPPET_CHARS // 3)
        snippet = re.sub(r"\s+", " ", segment.shown[begin : begin + SNIPPET_CHARS]).strip()
        match = Match(segment.number, segment.heading[:120], hits, snippet, segment.position)
        found.append((hits, order, match))
    found.sort(key=lambda item: (-item[0], item[1]))
    return len(found), [item[2] for item in found[offset : offset + limit]]


def window(text: str, offset: int, limit: int) -> tuple[str, int | None]:
    """A piece of the text from `offset`, cut at a line break when one is near its end.

    The second value is where the next piece starts, or None when the text ends in this one.
    """
    end = offset + limit
    if end >= len(text):
        return text[offset:], None
    cut = text.rfind("\n", offset + limit // 2, end)
    if cut >= 0:
        end = cut + 1
    return text[offset:end].rstrip("\n"), end
