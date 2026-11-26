"""Which subscriptions accept the metadata of a document, without looking at
each of them. The inverse of an ordinary filter: every subscription carries its
own conditions and the document carries the values.

For each key and value there is the list of subscriptions that require it. A
subscription accepts the document if it is in as many lists as conditions it
has. The result is exactly that of `cumple_filtros`, which is the definition."""
from __future__ import annotations

import logging
import math
from collections.abc import Hashable

import numpy as np

from src.search.filters import cumple_filtros

logger = logging.getLogger("contextcrawl.matching")


class _Slots:
    """A set of slots as an array: adding and removing take constant time."""

    def __init__(self) -> None:
        self._items = np.empty(4, dtype=np.int64)
        self._size = 0

    def add(self, slot: int, places: np.ndarray) -> None:
        if self._size == len(self._items):
            self._items = np.concatenate([self._items, np.empty_like(self._items)])
        self._items[self._size] = slot
        places[slot] = self._size
        self._size += 1

    def remove(self, slot: int, places: np.ndarray) -> None:
        self._size -= 1
        last = self._items[self._size]
        self._items[places[slot]] = last
        places[last] = places[slot]

    @property
    def items(self) -> np.ndarray:
        return self._items[: self._size]


class _Intervals:
    """Closed intervals, found by a point inside them. An interval contains the
    point if it has started and has not ended: the ones that have started are a
    prefix of the starts in order, and the ones that have ended a prefix of the
    ends, so it takes two binary searches."""

    def __init__(self) -> None:
        self._starts = (np.empty(0), np.empty(0, dtype=np.int64))
        self._ends = (np.empty(0), np.empty(0, dtype=np.int64))
        self._pending: dict[int, tuple[float, float]] = {}
        self._removed: set[int] = set()

    def add(self, slot: int, low: float, high: float) -> None:
        self._settle_removed()
        self._pending[slot] = (low, high)

    def remove(self, slot: int) -> None:
        if slot in self._pending:
            del self._pending[slot]
        else:
            self._removed.add(slot)

    def _settle_removed(self) -> None:
        if self._removed:
            gone = np.fromiter(self._removed, dtype=np.int64)
            self._removed.clear()
            for name in ("_starts", "_ends"):
                points, slots = getattr(self, name)
                keep = ~np.isin(slots, gone)
                setattr(self, name, (points[keep], slots[keep]))

    def _settle(self) -> None:
        self._settle_removed()
        if self._pending:
            new = np.fromiter(self._pending, dtype=np.int64, count=len(self._pending))
            limits = np.array(list(self._pending.values()))
            self._pending.clear()
            for name, values in (("_starts", limits[:, 0]), ("_ends", limits[:, 1])):
                points, slots = getattr(self, name)
                order = np.argsort(values, kind="stable")
                at = np.searchsorted(points, values[order])
                setattr(self, name, (np.insert(points, at, values[order]), np.insert(slots, at, new[order])))

    def containing(self, point: float) -> tuple[np.ndarray, np.ndarray]:
        """The slots whose interval has started, and those of them that have ended."""
        self._settle()
        started = np.searchsorted(self._starts[0], point, side="right")
        ended = np.searchsorted(self._ends[0], point, side="left")
        return self._starts[1][:started], self._ends[1][:ended]


class _Key:
    """The conditions on one metadata key."""

    def __init__(self) -> None:
        self.places = np.empty(0, dtype=np.int64)  # of each slot in the list it is in
        self.equal: dict[Hashable, _Slots] = {}
        self.ranges = _Slots()
        self.intervals = _Intervals()


def _limits(value: str) -> tuple[float, float]:
    low, _, high = value.partition(",")
    return float(low) if low else -math.inf, float(high) if high else math.inf


def _hashable(value: object) -> bool:
    try:
        hash(value)
    except TypeError:
        return False
    return True


class FilterIndex:
    def __init__(self) -> None:
        self._filters: dict[int, dict] = {}
        self._keys: dict[str, _Key] = {}
        self._required = np.full(16, -1, dtype=np.int32)  # conditions of each slot, -1 if it is not in use
        self._unusual: set[int] = set()  # slots that are checked one by one

    def add(self, slot: int, filters: dict[str, dict]) -> None:
        if slot in self._filters:
            raise ValueError(f"slot {slot} is in use")
        if slot >= len(self._required):
            bigger = np.full(max(slot + 1, 2 * len(self._required)), -1, dtype=np.int32)
            bigger[: len(self._required)] = self._required
            self._required = bigger
        self._filters[slot] = filters
        self._required[slot] = len(filters)
        if not all(self._is_usual(f) for f in filters.values()):
            self._unusual.add(slot)
            return
        for name, condition in filters.items():
            key = self._keys.setdefault(name, _Key())
            if slot >= len(key.places):
                bigger = np.zeros(len(self._required), dtype=np.int64)
                bigger[: len(key.places)] = key.places
                key.places = bigger
            if condition["tipo"] == "seleccion":
                key.equal.setdefault(condition["valor"], _Slots()).add(slot, key.places)
            else:
                key.ranges.add(slot, key.places)
                low, high = _limits(condition["valor"])
                if low <= high:  # otherwise it contains nothing
                    key.intervals.add(slot, low, high)

    def remove(self, slot: int) -> None:
        filters = self._filters.pop(slot)
        self._required[slot] = -1
        if slot in self._unusual:
            self._unusual.remove(slot)
            return
        for name, condition in filters.items():
            key = self._keys[name]
            if condition["tipo"] == "seleccion":
                slots = key.equal[condition["valor"]]
                slots.remove(slot, key.places)
                if not len(slots.items):
                    del key.equal[condition["valor"]]
            else:
                key.ranges.remove(slot, key.places)
                low, high = _limits(condition["valor"])
                if low <= high:
                    key.intervals.remove(slot)

    def of(self, slot: int) -> dict[str, dict]:
        return self._filters[slot]

    @staticmethod
    def _is_usual(condition: dict) -> bool:
        if condition["tipo"] == "seleccion":
            return _hashable(condition["valor"])
        try:
            low, high = _limits(condition["valor"])
        except (ValueError, AttributeError):
            return False
        return not (math.isnan(low) or math.isnan(high))

    def allowed(self, metadata: dict) -> np.ndarray:
        """1 for each slot whose conditions the metadata satisfies, else 0."""
        met = np.zeros(len(self._required), dtype=np.int32)
        for name, key in self._keys.items():
            value = metadata.get(name)
            if key.equal and _hashable(value) and value in key.equal:
                met[key.equal[value].items] += 1
            if len(key.ranges.items):
                self._count_ranges(key, value, met)
        mask = (met == self._required).astype(np.uint8)
        for slot in self._unusual:
            mask[slot] = self._check(slot, metadata)
        return mask

    @staticmethod
    def _count_ranges(key: _Key, value: object, met: np.ndarray) -> None:
        if value is None:
            return
        try:
            point = float(value)
        except (TypeError, ValueError, OverflowError):
            return
        if math.isnan(point):  # neither below nor above anything
            met[key.ranges.items] += 1
            return
        started, ended = key.intervals.containing(point)
        met[started] += 1
        met[ended] -= 1

    def _check(self, slot: int, metadata: dict) -> bool:
        try:
            return cumple_filtros(metadata, self._filters[slot])
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning("A subscription has a filter that cannot be evaluated: %s", exc)
            return False
