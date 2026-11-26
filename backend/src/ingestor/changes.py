"""Whether a record that arrives again is the one that is stored."""
from __future__ import annotations

import math
import unicodedata


def differences(text: str, metadata: dict, new_text: str, new_metadata: dict) -> list[str]:
    """The metadata keys whose value is not the same, and "texto" if the text is
    not. The order of the keys, the spacing and how a number is written do not
    count, and neither does a key that is only in the new record."""
    changed = [key for key in metadata if key not in new_metadata or not _same(metadata[key], new_metadata[key])]
    return (["texto"] if _plain(text) != _plain(new_text) else []) + sorted(changed)


def _plain(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _same(a: object, b: object) -> bool:
    if _is_number(a) or _is_number(b):
        # A number written as text is that number; two texts are only texts.
        return _number(a) is not None and _number(a) == _number(b)
    if type(a) is not type(b):
        return False
    if isinstance(a, str):
        return _plain(a) == _plain(b)
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[key], b[key]) for key in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def _number(value: object) -> float | None:
    if not (_is_number(value) or isinstance(value, str)):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None
