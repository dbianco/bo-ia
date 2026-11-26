"""Accent- and case-insensitive tokens, shared by the offline embeddings, the
synthetic corpus and the lexical reference so they agree on what a word is."""
from __future__ import annotations

import re
import unicodedata

_COMBINING = re.compile("[\u0300-\u036f]")
_TOKEN = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    """a al ante con contra cual cuando de del desde donde e el ella en entre era es esa ese eso esta este esto
    fue ha hasta la las le lo los mas mediante no o para pero por que se segun ser si sin sobre son su sus tras
    traves u un una uno unos unas y ya""".split()
)


def fold(text: str) -> str:
    """Lower case without diacritics."""
    text = text.lower()
    if text.isascii():
        return text
    return _COMBINING.sub("", unicodedata.normalize("NFKD", text))


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(fold(text))


def content_tokens(text: str) -> list[str]:
    return [t for t in tokens(text) if t not in STOPWORDS]
