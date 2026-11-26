"""Finds the subscriptions that a document matches: a reverse search, in which
the stored items are queries and the incoming item is the document.

The filters say which subscriptions may match (exactly), and a threshold search
over their vectors from every fragment of the document says which do. Scores are
always computed exactly, so a match that is reported is a match; with a graph
(many subscriptions, few of them left out by the filters) some may be missed."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from threading import RLock

import numpy as np

from src.matching.filter_index import FilterIndex
from src.vector.hnsw import DEFAULT_SLACK, DEFAULT_UPPER_EF, GRAPH_FROM, VectorIndex

DEFAULT_EF = 32
BEST_CHUNK = 4096
TIE_DECIMALS = 6


class SubscriptionIndex:
    """Subscriptions are rows of a vector index. Pausing only marks the row.
    Deleting leaves it unused, and the rows are renumbered when more than half
    of them, and at least `compact_from`, are."""

    def __init__(
        self,
        dim: int,
        *,
        graph_from: int = GRAPH_FROM,
        exact_below: int | None = None,
        ef: int = DEFAULT_EF,
        slack: float = DEFAULT_SLACK,
        upper_ef: int = DEFAULT_UPPER_EF,
        compact_from: int = 10_000,
        capacity: int = 1024,
    ) -> None:
        self._dim = dim
        self._graph_from = graph_from
        self._exact_below = exact_below
        self._ef = ef
        self._slack = slack
        self._upper_ef = upper_ef
        self._compact_from = compact_from
        self._lock = RLock()
        self._start(capacity)

    def _start(self, capacity: int) -> None:
        self._vectors = VectorIndex(self._dim, graph_from=self._graph_from, capacity=capacity)
        self._filters = FilterIndex()
        self._row_of: dict[int, int] = {}
        self._identifiers = np.full(max(capacity, 16), -1, dtype=np.int64)
        self._active = np.zeros(max(capacity, 16), dtype=np.uint8)

    def __len__(self) -> int:
        return len(self._row_of)

    def __contains__(self, identifier: int) -> bool:
        return identifier in self._row_of

    @property
    def rows(self) -> int:
        """Rows in use or waiting to be dropped."""
        return len(self._vectors)

    def add(self, identifier: int, vector: Sequence[float], filters: dict, *, active: bool = True) -> None:
        self.add_many([(identifier, vector, filters, active)])

    def add_many(self, items: Iterable[tuple[int, Sequence[float], dict, bool]]) -> None:
        """Adds subscriptions, or replaces the ones that are already there."""
        items = list(items)
        if not items:
            return
        matrix = _unit(np.array([vector for _, vector, _, _ in items], dtype=np.float32))
        with self._lock:
            for identifier, _, _, _ in items:
                self._forget(identifier)
            rows = self._vectors.add(matrix)
            if rows.stop > len(self._active):
                size = max(rows.stop, 2 * len(self._active))
                self._active = np.concatenate([self._active, np.zeros(size - len(self._active), dtype=np.uint8)])
                self._identifiers = np.concatenate(
                    [self._identifiers, np.full(size - len(self._identifiers), -1, dtype=np.int64)]
                )
            for row, (identifier, _, filters, active) in zip(rows, items, strict=True):
                self._row_of[identifier] = row
                self._identifiers[row] = identifier
                self._active[row] = active
                self._filters.add(row, filters)
            self._compact_if_needed()

    def set_active(self, identifier: int, active: bool) -> bool:
        """Pauses or resumes. Returns whether that changed anything."""
        with self._lock:
            row = self._row_of[identifier]
            changed = bool(self._active[row]) != active
            self._active[row] = active
            return changed

    def is_same(self, identifier: int, vector: np.ndarray, filters: dict) -> bool:
        """Whether it is stored with this vector and these filters."""
        with self._lock:
            row = self._row_of.get(identifier)
            if row is None or self._filters.of(row) != filters:
                return False
            return np.array_equal(self._vectors.vectors[row], _unit(np.atleast_2d(vector).astype(np.float32))[0])

    def remove(self, identifier: int) -> None:
        with self._lock:
            self._forget(identifier)
            self._compact_if_needed()

    def _forget(self, identifier: int) -> None:
        row = self._row_of.pop(identifier, None)
        if row is not None:
            self._active[row] = 0
            self._identifiers[row] = -1
            self._filters.remove(row)

    def _compact_if_needed(self) -> None:
        unused = len(self._vectors) - len(self._row_of)
        if unused < self._compact_from or unused * 2 <= len(self._vectors):
            return
        kept = sorted(self._row_of.items(), key=lambda item: item[1])
        rows = np.array([row for _, row in kept], dtype=np.int64)
        vectors, active = self._vectors.vectors[rows], self._active[rows]
        filters = [self._filters.of(row) for row in rows.tolist()]
        self._start(len(kept))
        self.add_many(
            (identifier, vector, own, bool(a))
            for (identifier, _), vector, own, a in zip(kept, vectors, filters, active, strict=True)
        )

    def match_exactly(self, metadata: dict, fragments: np.ndarray, threshold: float) -> dict[int, float]:
        """Like `match`, looking at every subscription that passes the filters."""
        return self._match(metadata, fragments, threshold, exact_below=len(self._vectors))

    def best_fragments(self, identifiers: Sequence[int], fragments: np.ndarray) -> dict[int, int]:
        """Which fragment is the nearest to each subscription: the first, if several tie."""
        fragments = _unit(np.asarray(fragments, dtype=np.float32).reshape(-1, self._dim))
        with self._lock:
            best: dict[int, int] = {}
            for start in range(0, len(identifiers), BEST_CHUNK):
                chunk = identifiers[start : start + BEST_CHUNK]
                rows = np.array([self._row_of[i] for i in chunk], dtype=np.int64)
                scores = np.round(self._vectors.vectors[rows] @ fragments.T, TIE_DECIMALS)
                best.update(zip(chunk, scores.argmax(axis=1).tolist(), strict=True))
            return best

    def vectors_in_order(self) -> np.ndarray:
        """The stored vectors, by row."""
        return self._vectors.vectors

    def match(self, metadata: dict, fragments: np.ndarray, threshold: float) -> dict[int, float]:
        """Subscription -> best score over the fragments, for those that match."""
        return self._match(metadata, fragments, threshold, exact_below=self._exact_below)

    def _match(
        self, metadata: dict, fragments: np.ndarray, threshold: float, *, exact_below: int | None
    ) -> dict[int, float]:
        fragments = np.asarray(fragments, dtype=np.float32).reshape(-1, self._dim)
        with self._lock:
            if not len(self._row_of) or not len(fragments):
                return {}
            allowed = self._filters.allowed(metadata)
            total = len(self._vectors)
            mask = np.zeros(total, dtype=np.uint8)
            mask[: min(total, len(allowed))] = allowed[:total]
            mask &= self._active[:total]
            rows, scores = self._vectors.search_threshold(
                _unit(fragments),
                threshold,
                ef=self._ef,
                slack=self._slack,
                upper_ef=self._upper_ef,
                allowed=mask,
                exact_below=exact_below,
            )
            return dict(zip(self._identifiers[rows].tolist(), scores.tolist(), strict=True))


def _unit(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)
