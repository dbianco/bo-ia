"""Metadata filters of the search engine: which rows may be in the result.

For each key and value, the rows that have it, as sorted arrays that become a
bitmap when they are used; for numbers, the values in order. Conditions on
several keys must all hold, and the values of one key are alternatives, as the
API defines. It is the engine's version of `aplicar_filtros`."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from src.config.installation import Filtro, FiltroSeleccion
from src.search.filters import FiltroNoDeclarado, limites_de_rango

CACHED_BITMAPS = 32


@dataclass
class Condition:
    """Either one of some values, or a number between two limits (either may be missing)."""

    values: list[str] = field(default_factory=list)
    low: float | None = None
    high: float | None = None

    @property
    def is_range(self) -> bool:
        return not self.values


def resolve(requested: Mapping[str, str], declared: Sequence[Filtro]) -> dict[str, Condition]:
    """The conditions that a request asks for, with the same errors as always."""
    by_key = {f.clave: f for f in declared}
    conditions = {}
    for key, value in requested.items():
        declaration = by_key.get(key)
        if declaration is None:
            raise FiltroNoDeclarado(key)
        if isinstance(declaration, FiltroSeleccion):
            conditions[key] = Condition(values=[value])
        else:
            low, high = limites_de_rango(declaration, value)
            if low is not None or high is not None:
                conditions[key] = Condition(low=low, high=high)
    return conditions


class _Ranges:
    """Runs of consecutive rows in order of a point (the first row, or a number)."""

    def __init__(self) -> None:
        self._points = np.empty(0)
        self._firsts = np.empty(0, dtype=np.int64)
        self._counts = np.empty(0, dtype=np.int64)
        self._added: dict[int, tuple[float, int]] = {}
        self._removed: set[int] = set()
        self.version = 0

    def add(self, point: float, first: int, count: int) -> None:
        if first in self._removed:
            self._settle()
        self._added[first] = (point, count)
        self.version += 1

    def remove(self, first: int) -> None:
        if self._added.pop(first, None) is None:
            self._removed.add(first)
        self.version += 1

    def _settle(self) -> None:
        if self._removed:
            keep = ~np.isin(self._firsts, np.fromiter(self._removed, dtype=np.int64))
            self._points, self._firsts, self._counts = self._points[keep], self._firsts[keep], self._counts[keep]
            self._removed.clear()
        if self._added:
            firsts = np.fromiter(self._added, dtype=np.int64, count=len(self._added))
            points = np.array([p for p, _ in self._added.values()])
            counts = np.array([c for _, c in self._added.values()], dtype=np.int64)
            self._added.clear()
            order = np.argsort(points, kind="stable")
            at = np.searchsorted(self._points, points[order])
            self._points = np.insert(self._points, at, points[order])
            self._firsts = np.insert(self._firsts, at, firsts[order])
            self._counts = np.insert(self._counts, at, counts[order])

    def rows(self, low: float | None = None, high: float | None = None) -> np.ndarray:
        self._settle()
        start = 0 if low is None else np.searchsorted(self._points, low, side="left")
        end = len(self._points) if high is None else np.searchsorted(self._points, high, side="right")
        firsts, counts = self._firsts[start:end], self._counts[start:end]
        if not len(firsts):
            return firsts
        ends = np.cumsum(counts)
        return np.repeat(firsts - (ends - counts), counts) + np.arange(ends[-1])


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return None if number != number else number


class MetadataIndex:
    def __init__(self) -> None:
        self._rows = 0
        self._hidden = 0
        self._alive = np.zeros(1024, dtype=np.uint8)
        self._days = np.zeros(1024, dtype=np.int32)
        self._values: dict[tuple[str, str], _Ranges] = {}
        self._numbers: dict[str, _Ranges] = {}
        self._metadata: dict[int, dict] = {}
        self._bitmaps: OrderedDict[tuple, np.ndarray] = OrderedDict()

    def __len__(self) -> int:
        return self._rows

    def add(self, metadata: dict, day: int, count: int) -> int:
        """Adds `count` consecutive rows and returns the first."""
        first = self._rows
        self._rows += count
        if self._rows > len(self._alive):
            size = max(self._rows, 2 * len(self._alive))
            for name in ("_alive", "_days"):
                old = getattr(self, name)
                bigger = np.zeros(size, dtype=old.dtype)
                bigger[:first] = old[:first]
                setattr(self, name, bigger)
        self._alive[first : self._rows] = 1
        self._days[first : self._rows] = day
        self._index(first, count, metadata)
        return first

    def remove(self, first: int, count: int) -> None:
        self._alive[first : first + count] = 0
        self._hidden += count
        self._unindex(first)

    def update(self, first: int, count: int, metadata: dict, day: int) -> None:
        self._days[first : first + count] = day
        if metadata != self._metadata[first]:
            self._unindex(first)
            self._index(first, count, metadata)

    def of(self, first: int) -> tuple[dict, int]:
        return self._metadata[first], int(self._days[first])

    def _index(self, first: int, count: int, metadata: dict) -> None:
        self._metadata[first] = metadata
        for key, value in metadata.items():
            if isinstance(value, str):
                self._values.setdefault((key, value), _Ranges()).add(first, first, count)
            number = _number(value)
            if number is not None:
                self._numbers.setdefault(key, _Ranges()).add(number, first, count)

    def _unindex(self, first: int) -> None:
        for key, value in self._metadata.pop(first).items():
            if isinstance(value, str):
                self._values[(key, value)].remove(first)
            if _number(value) is not None:
                self._numbers[key].remove(first)

    def mask(
        self, conditions: Mapping[str, Condition], *, date_from: int | None = None, date_to: int | None = None
    ) -> np.ndarray | None:
        """1 for each row that may be in the result. None if every row may."""
        if not conditions and date_from is None and date_to is None and not self._hidden:
            return None
        mask = self._alive[: self._rows].copy()
        if date_from is not None:
            mask &= self._days[: self._rows] >= date_from
        if date_to is not None:
            mask &= self._days[: self._rows] <= date_to
        for key, condition in conditions.items():
            if condition.is_range:
                found = np.zeros(self._rows, dtype=np.uint8)
                if key in self._numbers:
                    found[self._numbers[key].rows(condition.low, condition.high)] = 1
                mask &= found
                continue
            bitmaps = [self._bitmap(key, value) for value in condition.values]
            mask &= bitmaps[0] if len(bitmaps) == 1 else np.bitwise_or.reduce(bitmaps)
        return mask

    def _bitmap(self, key: str, value: str) -> np.ndarray:
        rows = self._values.get((key, value))
        name = (key, value, rows.version if rows else -1, self._rows)
        bitmap = self._bitmaps.get(name)
        if bitmap is None:
            bitmap = np.zeros(self._rows, dtype=np.uint8)
            if rows is not None:
                bitmap[rows.rows()] = 1
            self._bitmaps[name] = bitmap
            while len(self._bitmaps) > CACHED_BITMAPS:
                self._bitmaps.popitem(last=False)
        return bitmap
