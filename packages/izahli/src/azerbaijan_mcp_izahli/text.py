"""Text rules for the dictionary: Azerbaijani case folding, headword spellings and the layout of
an entry. Plain functions with no database and no MCP, so each rule can be tested alone."""

import itertools
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

_ACCENT_FREE = str.maketrans("əıöüçşğ", "eioucsg")
_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_SUPERSCRIPTS = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]")
_SUPERSCRIPT_TAIL = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+$")
_DIGIT_TAIL = re.compile(r"(?<=\D)\d{1,2}$")  # the homonym number as printed in "çay2"
# What a person or a program types where the dictionary has a plain hyphen, and what is invisible.
_DASHES = (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212)  # hyphens, dashes, minus
_INVISIBLE = (0xAD, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0xFEFF)  # soft hyphen, marks
_TYPED = {**dict.fromkeys(_DASHES, "-"), **dict.fromkeys(_INVISIBLE, None)}
_NO_BRACKETS = str.maketrans("", "", "()[]")
_CURLY_QUOTES = "".join(map(chr, (0x2018, 0x2019, 0x201A, 0x2039, 0x203A)))
_EDGE = " \t\r\n.,;:!?\"'«»“”„()[]{}…" + _CURLY_QUOTES
_LETTER = r"[^\W_]"  # a letter or a digit
_WORD = rf"{_LETTER}+"
_QUERY_WORD = re.compile(_WORD)
_OPTIONAL_LETTERS = re.compile(rf"(?<={_LETTER})[(\[][^)\]]*[)\]]")  # the (LÜ) of ACGÖZ(LÜ)
_TOKEN = re.compile(rf"{_WORD}(?:-{_WORD})*")
# A line that ends in a hyphen and goes on in lower case: the word is cut by the line, or is a
# compound that happens to break at its hyphen.
_WRAP_POINT = re.compile(r"-\n(?=[a-zəıöüçşğ])")
_WORD_BEFORE = re.compile(rf"{_WORD}(?:-{_WORD})*$")
_WORD_AFTER = re.compile(rf"[a-zəıöüçşğ]{_LETTER}*")
_SPACES = re.compile(r"\s+")
_SPACED_BAX = re.compile(r"\b([bB]) a x\b")
# The etymology note opens the entry or follows its labels ("is. [ər.] ...", "sif. və zərf [fars.]
# ..."). Labels are lower case, or the capitals of a variant headword; a capitalised word is the
# start of the definition, and "bax" starts a pointer. A bracket that ends in a colon names the
# speaker of a quotation ("[Vaqif:]"), not an origin.
_LABEL = r"(?!bax\b)(?:[a-zəıöüçşğ]{1,8}\.?|[A-ZƏİÖÜÇŞĞ]{2,8}\.?)"
_ORIGIN = re.compile(rf"(?:{_LABEL}\s+){{0,4}}\[([^\]:]{{1,80}})\]")
_POINTER = re.compile(r"(?<![\w,])bax\s+([a-zəıöüçşğ][^.;:□\n]*)")
_POINTER_AFTER = ".;:/)](-□" + chr(0x2013) + chr(0x2014)  # what may stand before a pointer's bax
_POINTER_LEAD = re.compile(r"(?:(?:[^\W\d_]{1,8}\.?|\d\.|\[[^\]]*\])\s+)*")
_HOMONYM_TAIL = re.compile(r"(\D+?)(\d{1,2})")
_REDIRECT = re.compile(r"(?:(?:[^\W\d_]{1,8}\.?|\d\.|\[[^\]]*\])\s+){0,4}?bax\s+[a-zəıöüçşğ]")
_GROUP = re.compile(r"[(\[]([^)\]]*)[)\]]")
MAX_QUERY_WORDS = 12
MAX_GROUPS = 4
MAX_POINTER = 80
STEM_LENGTH = 5
EXACT_BELOW = 4  # words shorter than this are matched whole


def fold(text: str) -> str:
    """Lower-case the Azerbaijani way: I becomes ı and İ becomes i.

    Azerbaijani has a dotted and a dotless i, so str.lower() alone is wrong for I: it gives i. An
    i followed by a combining dot above, which is what lower() makes of İ, is the plain i again.
    """
    folded = unicodedata.normalize("NFC", text).replace("I", "ı").replace("İ", "i")
    return folded.replace("i" + chr(0x307), "i").lower()


def accent_free(text: str) -> str:
    """The loosest key: folded, without Azerbaijani accents and without hyphens."""
    return fold(text).translate(_ACCENT_FREE).replace("-", "")


def clean_headword(raw: str) -> str:
    """The headword as printed, without the colon or comma the extraction leaves behind it."""
    head = re.sub(r"\s+", " ", raw).strip().rstrip(",;:").rstrip()
    return re.sub(r",(?=\S)", ", ", head)


def display_headword(raw: str, homonym: int | None) -> str:
    """The headword with the superscript the dictionary puts on homonyms, such as ÇAY²."""
    mark = "" if homonym is None else str(homonym).translate(_SUPERSCRIPT)
    return clean_headword(raw) + mark


def strip_homonym_mark(headword: str) -> str:
    """A displayed headword without its superscript: ÇAY² is ÇAY."""
    return _SUPERSCRIPT_TAIL.sub("", headword)


def headword_forms(raw: str) -> list[str]:
    """Every spelling a headword stands for, folded.

    `AB(B)ASI` is abası and abbası, `RAD[D]Ə` is radə and raddə, and `AB-HAVA,ABÜHAVA` is two words.
    """
    forms: dict[str, None] = {}
    for part in raw.translate(_TYPED).split(","):
        part = part.strip().strip(".!:;\"'…")
        if not part:
            continue
        pieces = _GROUP.split(part)
        fixed, groups = pieces[0::2], pieces[1::2]
        if len(groups) > MAX_GROUPS:
            choices: Iterable[tuple[bool, ...]] = [(False,) * len(groups), (True,) * len(groups)]
        else:
            choices = itertools.product((False, True), repeat=len(groups))
        for keep in choices:
            spelled = fixed[0] + "".join(
                (group if kept else "") + tail
                for group, kept, tail in zip(groups, keep, fixed[1:], strict=True)
            )
            form = fold(spelled).translate(_NO_BRACKETS).strip(_EDGE)
            if form:
                forms[form] = None
    return list(forms)


def query_forms(word: str) -> list[str]:
    """The spellings a typed word can stand for.

    A headword is typed as it is printed: `AB(B)ASI`, `ÇAY²`, `AB-HAVA, ABÜHAVA`. Other dashes and
    invisible characters are forgiven, and so is the homonym number glued to a word (`çay2`).
    """
    typed = _SPACES.sub(" ", word.translate(_TYPED)).strip()
    return headword_forms(_DIGIT_TAIL.sub("", _SUPERSCRIPT_TAIL.sub("", typed)))


def build_vocabulary(texts: Iterable[str], spellings: Iterable[str]) -> Counter[str]:
    """The words the dictionary itself uses, folded, with their hyphens.

    `spellings` are the folded forms of the headwords. Words cut by the end of a line are left
    out: the vocabulary is what decides how to join them.
    """
    vocabulary: Counter[str] = Counter()
    for text in texts:
        unbroken = "\n".join(text.splitlines()).replace("-\n", " ")
        vocabulary.update(_TOKEN.findall(fold(unbroken)))
    vocabulary.update(spellings)
    return vocabulary


def _keeps_hyphen(left: str, right: str, vocabulary: Mapping[str, int]) -> bool:
    """Whether a word broken at a hyphen is a compound that is written with it."""
    hyphenated = vocabulary.get(fold(f"{left}-{right}"), 0)
    joined = vocabulary.get(fold(left + right), 0)
    if hyphenated or joined:
        return hyphenated > joined
    # Neither spelling occurs elsewhere. A doubled word (aşkar-aşkar), a number with its ending
    # (1931-ci) and the prefix qeyri- are always written with the hyphen; anything else was cut.
    return (
        any(char.isdigit() for char in left)
        or (len(right) >= 3 and fold(left) == fold(right))
        or (len(right) >= 3 and fold(left) == "qeyri")
    )


def dewrap(text: str, vocabulary: Mapping[str, int]) -> str:
    """Join the lines of an entry into one running text.

    The PDF breaks lines inside words, with a hyphen. The hyphen goes, unless the dictionary
    elsewhere spells the word with it more often than without (ata-baba): then it belongs there.
    """
    text = "\n".join(unicodedata.normalize("NFC", text).splitlines())
    pieces: list[str] = []
    last = 0
    for point in _WRAP_POINT.finditer(text):
        start = point.start()
        left = _WORD_BEFORE.search(text, max(0, start - 40), start)
        right = _WORD_AFTER.match(text, point.end())
        keep = True  # a hyphen with no word before it is not a break in a word
        if left and right:
            keep = _keeps_hyphen(left[0], right[0], vocabulary)
        pieces.append(text[last:start])
        pieces.append("-" if keep else "")
        last = point.end()
    pieces.append(text[last:])
    text = re.sub(r"-\n(?=\S)", "-", "".join(pieces))
    text = _SPACES.sub(" ", text).strip()
    # The word "bax" is set in letter-spaced italics, which the PDF text layer spells out.
    return _SPACED_BAX.sub(lambda match: match[1] + "ax", text)


def origin_of(text: str) -> str | None:
    """The etymology note in square brackets that opens an entry, such as `fars.`."""
    match = _ORIGIN.match(text)
    return match[1].strip() if match else None


@dataclass(frozen=True)
class Pointer:
    """A "bax" (see) reference to another headword."""

    text: str  # as printed, for example "dərd 3-cü mənada"
    forms: tuple[str, ...]  # folded spellings to look up, the likeliest first
    homonym: int | None = None  # the number in "acımaq1", when there is one


def _points_here(text: str, start: int) -> bool:
    """Whether the "bax" at `start` is a pointer and not the verb in a quotation.

    A pointer opens the entry or follows its labels, a dash, a sense number or a bracket. The
    verb follows a comma or a word: "sən də bax bu gözə".
    """
    before = text[:start].rstrip()
    if not before or before[-1] in _POINTER_AFTER:
        return True
    return _POINTER_LEAD.fullmatch(text[:start]) is not None


def pointers(text: str) -> list[Pointer]:
    """The headwords an entry sends the reader to with "bax"."""
    found: dict[str, Pointer] = {}
    for match in _POINTER.finditer(text):
        if not _points_here(text, match.start()):
            continue
        target = match[1]
        if len(target) > MAX_POINTER:
            target = target[:MAX_POINTER].rsplit(" ", 1)[0]  # not in the middle of a word
        for part in target.split(","):
            part = part.strip()
            while part.endswith(")") and part.count(")") > part.count("("):
                part = part[:-1].rstrip()  # the bracket that closes "(bax ...)"
            if not part:
                continue
            words = part.split()
            head, homonym = words[0], None
            if tail := _HOMONYM_TAIL.fullmatch(head):
                head, homonym = tail[1], int(tail[2])
            # "dərd 3-cü mənada": the words before the first number name the headword.
            phrase = " ".join([head, *itertools.takewhile(lambda w: not w[0].isdigit(), words[1:])])
            forms = tuple(dict.fromkeys([*headword_forms(phrase), *headword_forms(head)]))
            found.setdefault(part, Pointer(part, forms, homonym))
    return list(found.values())


def is_redirect(text: str) -> bool:
    """Whether an entry begins by sending the reader elsewhere: `bax X.`, after its labels."""
    return _REDIRECT.match(text) is not None


def window(text: str, offset: int, size: int) -> tuple[str, int | None]:
    """A piece of at most `size` characters from `offset`, cut at a space when it can be.

    Also where the next piece starts, or None when this one reaches the end.
    """
    if offset >= len(text):
        return "", None
    end = offset + size
    if end >= len(text):
        return text[offset:], None
    cut = text.rfind(" ", offset + size // 2, end)
    if cut == -1:
        return text[offset:end], end
    return text[offset:cut], cut + 1


def _fold_in_place(text: str) -> str:
    """fold() for text already in NFC: same length, so positions map back onto the text."""
    turkic = text.replace("I", "ı").replace("İ", "i")
    folded = turkic.lower()
    if len(folded) == len(text):
        return folded
    return "".join(low if len(low := char.lower()) == 1 else char for char in turkic)


def snippet(text: str, patterns: Iterable[str], width: int = 220) -> str:
    """A passage of the text around the first place one of the search patterns occurs."""
    if len(text) <= width:
        return text
    folded = _fold_in_place(text)
    hits = [found.start() for pattern in patterns if (found := re.search(pattern, folded))]
    start = max(0, min(hits, default=0) - width // 4)
    if start:
        start = text.rfind(" ", 0, start) + 1
    end = min(len(text), start + width)
    if end < len(text):
        cut = text.find(" ", end)
        end = len(text) if cut == -1 else cut
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def query_words(query: str) -> list[str]:
    """The words of a search query, folded.

    A headword typed as printed is read without its optional letters (`ACGÖZ(LÜ)` is acgöz), and
    the homonym number of `ÇAY²` is dropped.
    """
    cleaned = _SUPERSCRIPTS.sub("", _OPTIONAL_LETTERS.sub("", fold(query)))
    return _QUERY_WORD.findall(cleaned)


def match_terms(words: Iterable[str], exact: bool) -> tuple[str, list[str]]:
    """An FTS5 expression for the words of a query, and patterns that find them in the text.

    Azerbaijani adds endings to words, so a word of four letters or more is matched by its first
    five letters as a prefix, a cheap stemmer that suits a language of endings. With exact, words
    are matched whole. The patterns are for folded text and start at the beginning of a word.
    """
    terms, patterns = [], []
    for word in words:
        if exact or len(word) < EXACT_BELOW:
            terms.append(f'"{word}"')
            patterns.append(rf"(?<!{_LETTER}){re.escape(word)}(?!{_LETTER})")
        else:
            stem = word[:STEM_LENGTH]
            terms.append(f'"{stem}"*')
            patterns.append(rf"(?<!{_LETTER}){re.escape(stem)}")
    return " AND ".join(terms), patterns


def edit_distance(a: str, b: str, limit: int) -> int | None:
    """The number of edits (insert, delete, replace, swap two neighbours) from a to b, or None
    when it is more than `limit`."""
    if abs(len(a) - len(b)) > limit:
        return None
    before: list[int] | None = None
    row = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i, *([0] * len(b))]
        for j, right in enumerate(b, 1):
            value = min(row[j] + 1, current[j - 1] + 1, row[j - 1] + (left != right))
            if before is not None and i > 1 and j > 1 and left == b[j - 2] and a[i - 2] == right:
                value = min(value, before[j - 2] + 1)
            current[j] = value
        if min(current) > limit:
            return None
        before, row = row, current
    return row[-1] if row[-1] <= limit else None
