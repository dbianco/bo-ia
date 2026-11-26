"""Splits an issue of the Córdoba gazette into its notices.

Each notice ends with a closing line such as
`3 días - Nº 688209 - s/c - 24/9/2026 - BOE`: publication days, notice number,
fee and last publication date. Everything that is in no notice goes to another
segment, so that every character of the text belongs to exactly one."""
from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from src.text.tokens import fold

# Spaces are allowed where the extractor adds them between some glyphs ("27 /9/2026").
_CLOSING = re.compile(
    r"""\s*(?P<days>\d{1,3})\s*d[ií]as?
    \s*[-–—]\s*N\s*[º°o.]{1,2}\s*(?P<number>\d[\d\s]*?)
    \s*[-–—]\s*(?:s\s*/\s*c|\$\s*[\d.,\s]+?)
    \s*[-–—]\s*(?P<day>\d{1,2})\s*/\s*(?P<month>\d{1,2})\s*/\s*(?P<year>\d{4})
    \s*[-–—]\s*BOE\s*\.?\s*""",
    re.IGNORECASE | re.VERBOSE,
)
_CLOSING_START = re.compile(r"\s*\d{1,3}\s*d[ií]as?\s*[-–—]\s*N", re.IGNORECASE)
_CONTENTS = re.compile(r"(?P<title>.+?)\s*\.{4,}\s*P[aá]g\.?\s*\d+\s*$", re.IGNORECASE)
_BEFORE_CONTENTS = {"redes de", "contacto boe"}
_TOWN = re.compile(r"(?:MUNICIPALIDAD|COMUNA) DE (?:LA (?:CIUDAD|LOCALIDAD) DE )?(?P<town>[^.,;:\d]+?)\s*\.?$")
_SMALL_WORDS = {"de", "del", "la", "las", "el", "los", "y"}

MAX_HEADING_LINES = 4


@dataclass(frozen=True)
class ClosingLine:
    number: str
    days: int
    last_date: date


def parse_closing(line: str) -> ClosingLine | None:
    match = _CLOSING.fullmatch(line)
    if match is None:
        return None
    try:
        last = date(int(match["year"]), int(match["month"]), int(match["day"]))
    except ValueError:
        return None
    return ClosingLine("".join(match["number"].split()), int(match["days"]), last)


@dataclass
class Segment:
    """Part of an issue. A notice that surrounds the table of contents has two spans."""

    spans: list[tuple[int, int]]
    text: str
    page_starts: list[tuple[int, int]]  # (offset in `text`, page), ascending

    @property
    def first_page(self) -> int:
        return self.page_starts[0][1]

    @property
    def last_page(self) -> int:
        return self.page_starts[-1][1]


@dataclass
class Notice(Segment):
    closing: ClosingLine
    heading: str | None = None
    town: str | None = None

    @property
    def number(self) -> str:
        return self.closing.number

    @property
    def days(self) -> int:
        return self.closing.days

    @property
    def last_date(self) -> date:
        return self.closing.last_date


@dataclass
class Segmentation:
    text: str
    notices: list[Notice] = field(default_factory=list)
    front_matter: Segment | None = None  # masthead and table of contents
    unsegmented: Segment | None = None

    @property
    def parts(self) -> list[Segment]:
        others = [s for s in (self.front_matter, self.unsegmented) if s is not None]
        return [*others, *self.notices]


@dataclass
class _Line:
    start: int
    end: int  # after the line break
    page: int
    text: str


def _lines(text: str, page_offsets: Sequence[int]) -> list[_Line]:
    lines, start = [], 0
    for raw in text.splitlines(keepends=True) if "\n" in text else [text]:
        end = start + len(raw)
        lines.append(_Line(start, end, bisect_right(page_offsets, start), raw.strip()))
        start = end
    return lines


def _front_matter(lines: list[_Line]) -> tuple[set[int], set[str]]:
    """Positions of the cover lines that are in no notice, and the section
    headings that the table of contents names."""
    cover = [i for i, line in enumerate(lines) if line.page == 1]
    contents = [i for i in cover if _CONTENTS.match(lines[i].text)]
    headings = {fold(_CONTENTS.match(lines[i].text)["title"]) for i in contents}
    front = set(contents)
    if contents:
        before = contents[0] - 1
        while before >= 0 and fold(lines[before].text) in _BEFORE_CONTENTS:
            front.add(before)
            before -= 1
    # The masthead ends where the first section that the contents name begins.
    first = next((i for i in cover if fold(lines[i].text) in headings), None)
    if first is None:
        first = next((i + 1 for i in cover if fold(lines[i].text).startswith("email: boe@")), 0)
    # Nothing past a closing line is masthead.
    closing = next((i for i in cover if parse_closing(lines[i].text)), len(lines))
    if first <= closing:
        front.update(range(first))
    return front, headings


def _closings(lines: list[_Line], body: list[int], issue_date: date) -> dict[int, ClosingLine]:
    """Body positions (indices into `body`) where a notice ends."""
    found: dict[int, ClosingLine] = {}
    at = 0
    while at < len(body):
        text = lines[body[at]].text
        closing, end = parse_closing(text), at
        if closing is None and at + 1 < len(body) and _CLOSING_START.match(text):
            closing, end = parse_closing(f"{text} {lines[body[at + 1]].text}"), at + 1
        if closing is not None and not _is_quoted(lines, body, at, end, closing, issue_date):
            found[end] = closing
            at = end
        at += 1

    # Two closing lines with one number: an erratum quotes a notice of its own issue.
    repeated = {number for number, times in Counter(c.number for c in found.values()).items() if times > 1}
    for end in [e for e, c in found.items() if c.number in repeated]:
        if _previous_text(lines, body, end).endswith(":"):
            del found[end]
    return found


def _previous_text(lines: list[_Line], body: list[int], at: int) -> str:
    return next((lines[i].text for i in reversed(body[:at]) if lines[i].text), "")


def _is_quoted(
    lines: list[_Line], body: list[int], at: int, end: int, closing: ClosingLine, issue_date: date
) -> bool:
    """A closing line that takes a whole line may still be part of the text of a
    notice that cites another one."""
    if closing.last_date < issue_date:
        return True  # a notice of this issue cannot have stopped being published before it
    before = _previous_text(lines, body, at)
    if before.endswith((",", "“", "«", "(")):
        return True
    after = next((lines[i].text for i in body[end + 1 :] if lines[i].text), "")
    return bool(after) and (after[0].islower() or after[0] in ",;.)”»")


def _is_upper(text: str) -> bool:
    return any(c.isalpha() for c in text) and text == text.upper()


def _heading(texts: Sequence[str], section_headings: set[str]) -> list[str]:
    """The lines in capitals that open a notice, without the heading of its section."""
    heading: list[str] = []
    for text in texts:
        if not text or (not heading and fold(text) in section_headings):
            continue
        if len(heading) == MAX_HEADING_LINES or not _is_upper(text) or parse_closing(text):
            break
        heading.append(text)
    return heading


def _town(heading: Sequence[str]) -> str | None:
    for line in heading:
        match = _TOWN.match(line)
        if match:
            words = match["town"].lower().split()
            return " ".join(w if i and w in _SMALL_WORDS else w.capitalize() for i, w in enumerate(words))
    return None


def _segment(text: str, lines: list[_Line], positions: Sequence[int]) -> Segment:
    spans: list[tuple[int, int]] = []
    pieces: list[str] = []
    page_starts: list[tuple[int, int]] = []
    offset = 0
    for position in positions:
        line = lines[position]
        if spans and spans[-1][1] == line.start:
            spans[-1] = (spans[-1][0], line.end)
        else:
            spans.append((line.start, line.end))
        # A blank line says nothing about where the segment is.
        if line.text and (not page_starts or page_starts[-1][1] != line.page):
            page_starts.append((offset if page_starts else 0, line.page))
        pieces.append(text[line.start : line.end])
        offset += line.end - line.start
    return Segment(spans, "".join(pieces), page_starts)


def segment(pages: Sequence[str], issue_date: date) -> Segmentation:
    """`pages` without running headers. The text of the issue is the pages
    joined by line breaks."""
    text = "\n".join(pages)
    result = Segmentation(text)
    if not text.strip():
        return result
    offsets, start = [], 0
    for page in pages:
        offsets.append(start)
        start += len(page) + 1
    lines = _lines(text, offsets)
    front, section_headings = _front_matter(lines)
    body = [i for i in range(len(lines)) if i not in front]
    closings = _closings(lines, body, issue_date)
    if not closings:
        # Another layout: the section is one document, cover included.
        result.unsegmented = _segment(text, lines, range(len(lines)))
        return result

    begin = 0
    groups: list[tuple[list[int], ClosingLine]] = []
    for end in sorted(closings):
        groups.append((body[begin : end + 1], closings[end]))
        begin = end + 1
    rest = body[begin:]
    if rest and not any(lines[i].text for i in rest):
        groups[-1][0].extend(rest)  # trailing blank lines
        rest = []

    for positions, closing in groups:
        part = _segment(text, lines, positions)
        heading = _heading([lines[i].text for i in positions], section_headings)
        result.notices.append(
            Notice(
                spans=part.spans,
                text=part.text,
                page_starts=part.page_starts,
                closing=closing,
                heading=" ".join(heading).rstrip(". ") or None,
                town=_town(heading),
            )
        )
    if rest:
        result.unsegmented = _segment(text, lines, rest)
    if any(lines[i].text for i in front):
        result.front_matter = _segment(text, lines, sorted(front))
    elif front:  # blank lines only: they belong to the first notice
        positions = sorted([*front, *groups[0][0]])
        first, part = result.notices[0], _segment(text, lines, positions)
        first.spans, first.text, first.page_starts = part.spans, part.text, part.page_starts
    return result
