"""Why a document matched a subscription: an excerpt of the fragment that did,
with the words they share. If they share none, the match is by meaning, and no
reason is invented."""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

from src.db.models import EvaluacionMatch
from src.engine.analyzer import analyze

EXCERPT_LENGTH = 400
LEAD = 80  # what is shown before the first shared word

_WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class Part:
    text: str
    match: bool


def _matches(text: str, query: str) -> list[tuple[int, int, str]]:
    """(start, end, term) of the words of the text that are in the query, in any form."""
    terms = set(analyze(query))
    found = []
    for word in _WORD.finditer(text):
        shared = [t for t in analyze(word.group()) if t in terms]
        if shared:
            found.append((word.start(), word.end(), shared[0]))
    return found


def highlight(text: str, query: str) -> list[Part]:
    """The text in parts, which joined are the text."""
    parts, at = [], 0
    for start, end, _ in _matches(text, query):
        if start > at:
            parts.append(Part(text[at:start], False))
        parts.append(Part(text[start:end], True))
        at = end
    if at < len(text):
        parts.append(Part(text[at:], False))
    return parts


def shared_words(text: str, query: str) -> list[str]:
    """As they are written in the text, each one once."""
    words: dict[str, str] = {}
    for start, end, term in _matches(text, query):
        words.setdefault(term, text[start:end])
    return list(words.values())


def excerpt_of(text: str, query: str) -> str:
    """A piece of the text, of whole words: the one with more of the words of the
    query, or the beginning if there are none."""
    text = text.strip()
    if len(text) <= EXCERPT_LENGTH:
        return text
    found = _matches(text, query)
    best, best_value = 0, (0, 0)
    for start, _, _ in found:
        begin = _word_start(text, max(0, start - LEAD))
        inside = [t for s, e, t in found if s >= begin and e <= begin + EXCERPT_LENGTH]
        value = (len(set(inside)), len(inside))
        if value > best_value:
            best, best_value = begin, value
    end = best + EXCERPT_LENGTH
    if end < len(text):
        # Back to the last space, unless there is none.
        cut = next((i for i in range(end, best, -1) if text[i].isspace()), 0)
        end = cut or end
    return text[best:end].strip()


def _word_start(text: str, at: int) -> int:
    """The first word that begins at or after a position."""
    if at == 0 or text[at - 1].isspace():
        return at
    for i in range(at, min(at + LEAD, len(text))):
        if text[i].isspace():
            return i + 1
    return at


@dataclass(frozen=True)
class Explanation:
    title: str
    url: str
    date: datetime.date
    notice_number: str | None
    page: int | None  # of the fragment
    first_page: int | None  # of the document
    last_page: int | None
    score: float
    filters: dict[str, str]
    excerpt: str
    parts: list[Part]
    shared_words: list[str]

    @property
    def citation(self) -> str:
        """Where in its publication the document is, if it is known."""
        words = []
        if self.notice_number:
            words.append(f"Aviso Nº {self.notice_number}")
        if self.first_page and self.first_page == self.last_page:
            words.append(f"Página {self.first_page}")
        elif self.first_page:
            words.append(f"Páginas {self.first_page} a {self.last_page}")
        return " — ".join(words)


def explain(match: EvaluacionMatch) -> Explanation:
    document, fragment, query = match.documento, match.fragmento, match.suscripcion.texto_busqueda
    # A match from before fragments were recorded, or whose fragment is gone.
    text = fragment.texto if fragment is not None else document.texto
    excerpt = excerpt_of(text, query)
    return Explanation(
        title=document.titulo or document.identificador_externo,
        url=document.url_fuente,
        date=document.fecha,
        notice_number=document.notice_number,
        page=fragment.page if fragment is not None else document.first_page,
        first_page=document.first_page,
        last_page=document.last_page,
        score=match.score,
        filters={key: str(f.get("valor")) for key, f in (match.filtros_aplicados or {}).items()},
        excerpt=excerpt,
        parts=highlight(excerpt, query),
        shared_words=shared_words(excerpt, query),
    )
