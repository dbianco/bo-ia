"""Page-by-page text of a PDF, and removal of running headers and footers.

Text is kept in content order, the order in which it was written into the file.
For a page in two columns that is the reading order; ordering by position on the
page would interleave them."""
from __future__ import annotations

import io
import math
import re
from collections.abc import Iterator, Sequence

from pypdf import PdfReader
from pypdf.errors import PdfReadError

# A header must repeat on this many pages, and on this share of them. Repetition
# on two pages proves nothing: two notices with one title may open both.
MIN_PAGES = 3
MIN_SHARE = 0.6

_PAGE = "\0page\0"  # stands for the page number in a key
_NUMBER = re.compile(r"\d+")


class ErrorExtraccionPDF(RuntimeError):
    """El PDF no se pudo leer o no tiene texto extraíble."""


def extract_pages(content: bytes) -> list[str]:
    try:
        reader = PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
    except (PdfReadError, ValueError, KeyError) as exc:
        raise ErrorExtraccionPDF(f"No se pudo leer el PDF: {exc}") from exc
    if not any(page.strip() for page in pages):
        raise ErrorExtraccionPDF("El PDF no tiene texto extraíble (¿está escaneado?)")
    return pages


def _keys(line: str, page: int) -> Iterator[str]:
    """What makes a line "the same" on two pages: its text, or its text with the
    number of its page left out."""
    text = " ".join(line.split())
    yield text
    for match in _NUMBER.finditer(text):
        if match.group() == str(page):
            yield f"{text[: match.start()]}{_PAGE}{text[match.end() :]}"


def _run_length(lines: Sequence[str], page: int, repeated: set[str], numbered: bool) -> tuple[int, bool]:
    """How many lines from the start are repeated ones (blank lines between them
    included), and whether the page number was among them. A page has one number:
    a second line that follows it is body text that happens to count upwards."""
    length = 0
    for position, line in enumerate(lines):
        if not line.strip():
            continue
        same = repeated.intersection(_keys(line, page))
        if not same:
            break
        if all(_PAGE in key for key in same):
            if numbered:
                break
            numbered = True
        length = position + 1
    return length, numbered


def _edge_runs(pages: Sequence[Sequence[str]], numbered: Sequence[bool]) -> tuple[list[int], list[bool]]:
    """Lines to remove from the start of each page, and which pages have shown their number."""
    quorum = max(MIN_PAGES, math.ceil(MIN_SHARE * len(pages)))

    def repeated_in(sections: Sequence[Sequence[str]]) -> set[str]:
        counts: dict[str, set[int]] = {}
        for number, lines in enumerate(sections, start=1):
            for line in lines:
                if line.strip():
                    for key in _keys(line, number):
                        counts.setdefault(key, set()).add(number)
        return {key for key, where in counts.items() if len(where) >= quorum}

    repeated = repeated_in(pages)
    while True:
        found = [
            _run_length(lines, number, repeated, done)
            for number, (lines, done) in enumerate(zip(pages, numbered, strict=True), start=1)
        ]
        runs = [length for length, _ in found]
        # Count again, only at the edge: what repeats inside the pages is body text.
        at_edge = repeated & repeated_in([lines[:run] for lines, run in zip(pages, runs, strict=True)])
        if at_edge == repeated:
            break
        repeated = at_edge

    # The body may start with one same title on many pages. A header appears only
    # at the edge, so whatever is also inside some page is not part of it.
    inside = {
        " ".join(line.split()) for lines, run in zip(pages, runs, strict=True) for line in lines[run:] if line.strip()
    }
    for number, lines in enumerate(pages):
        run = runs[number]
        while run and (not lines[run - 1].strip() or " ".join(lines[run - 1].split()) in inside):
            run -= 1
        runs[number] = run
    return runs, [done for _, done in found]


def remove_running_lines(pages: Sequence[str]) -> list[str]:
    """The same pages without headers and footers, which are found by their
    repetition. Body text is never removed: in doubt, a line stays."""
    if len(pages) < MIN_PAGES:
        return list(pages)
    split = [page.split("\n") for page in pages]
    runs, numbered = _edge_runs(split, [False] * len(split))
    split = [lines[run:] for lines, run in zip(split, runs, strict=True)]
    runs, _ = _edge_runs([lines[::-1] for lines in split], numbered)
    split = [lines[: len(lines) - run] for lines, run in zip(split, runs, strict=True)]
    return ["\n".join(lines) for lines in split]
