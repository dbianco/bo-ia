"""Search over unit vectors: exact while there are few, and a hierarchical
navigable small world graph (HNSW) from `graph_from` rows on. Filters apply
during the traversal, and a search may be by threshold besides top-k.

The graph works on 8-bit codes; similarities in the results are always exact.

Rows are numbered in the order in which they are added and never change. A row
is not removed from the graph, which would break the paths through it: callers
leave it out with the `allowed` mask.

Results are ordered by similarity and then by row. The graph is the same
whatever the number of threads that build it."""
from __future__ import annotations

import math
import os
import random
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from queue import Empty, SimpleQueue

import numpy as np

from src.vector.locks import ReadWriteLock

# The compiled kernels are imported where they are used: an installation with few
# vectors never loads the compiler.

THREADS = os.cpu_count() or 1
GRAPH_FROM = 20_000  # below this an exact scan takes a few milliseconds
BATCH = 256  # rows whose links are chosen at the same time
DEFAULT_EF = 64
DEFAULT_SLACK = 0.05
DEFAULT_UPPER_EF = 1024  # in the layer above: it decides how many separate regions are found
SEED_SLACK = 0.1
CODE_ERROR = 0.005  # a row this much below the threshold, by its code, may reach it
MIN_EXACT = 2_000
SCAN_BLOCK = 8_192

_NEVER = np.float32(np.inf)
_NO_FILTER = np.empty(0, dtype=np.uint8)
_NO_ROWS = np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float32)
_pool = ThreadPoolExecutor(THREADS, thread_name_prefix="vector-search")


class VectorIndex:
    def __init__(
        self,
        dim: int,
        *,
        m: int = 16,
        ef_construction: int = 100,
        seed: int = 0,
        capacity: int = 1024,
        graph_from: int = GRAPH_FROM,
    ) -> None:
        if m < 2 or ef_construction < m:
            raise ValueError("m must be at least 2 and ef_construction at least m")
        self.dim = dim
        self.m = m
        self.ef_construction = ef_construction
        self._graph_from = graph_from
        self._levels_rng = random.Random(f"hnsw:{seed}")
        self._scale = 1 / math.log(m)
        self._lock = ReadWriteLock()
        self._count = 0  # rows stored
        self.graph_rows = 0  # rows linked in the graph: the first ones
        self._entry = -1
        self._entry_level = -1
        self._vectors = np.zeros((max(capacity, 16), dim), dtype=np.float32)
        self._codes = np.empty((0, dim), dtype=np.int8)
        self._scales = np.empty(0, dtype=np.float32)
        self._links0 = np.empty(0, dtype=np.int32)
        self._levels = np.empty(0, dtype=np.int32)
        self._upper_start = np.empty(0, dtype=np.int64)
        self._upper_links = np.empty(0, dtype=np.int32)
        self._upper_used = 0
        self._scratch: SimpleQueue = SimpleQueue()

    def __len__(self) -> int:
        return self._count

    @property
    def vectors(self) -> np.ndarray:
        return self._vectors[: self._count]

    # --- construction ---

    def add(self, vectors: np.ndarray) -> range:
        """Adds unit vectors as rows and returns their numbers. Searches go on
        between one batch and the next."""
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[1] != self.dim:
            raise ValueError(f"expected rows of dimension {self.dim}")
        first = self._count
        with self._lock.write():
            self._store(vectors)
        if self._count >= max(self._graph_from, 1):
            while self.graph_rows < self._count:
                with self._lock.write():
                    self._reserve_graph()
                    self._link(self.graph_rows, min(BATCH, self._count - self.graph_rows))
        return range(first, self._count)

    def _store(self, vectors: np.ndarray) -> None:
        total = self._count + len(vectors)
        if total > len(self._vectors):
            bigger = np.zeros((max(total, 2 * len(self._vectors)), self.dim), dtype=np.float32)
            bigger[: self._count] = self.vectors
            self._vectors = bigger
        self._vectors[self._count : total] = vectors
        self._count = total

    def _reserve_graph(self) -> None:
        capacity = len(self._vectors)
        if len(self._levels) >= capacity:
            return

        def grown(array: np.ndarray, size: int, fill: int) -> np.ndarray:
            bigger = np.full(size, fill, dtype=array.dtype)
            bigger[: len(array)] = array
            return bigger

        codes = np.zeros((capacity, self.dim), dtype=np.int8)
        codes[: self.graph_rows] = self._codes[: self.graph_rows]
        self._codes = codes
        self._scales = grown(self._scales, capacity, 0)
        self._links0 = grown(self._links0, capacity * 2 * self.m, -1)
        self._levels = grown(self._levels, capacity, 0)
        self._upper_start = grown(self._upper_start, capacity, -1)

    def _place_upper(self, row: int, level: int) -> None:
        needed = self._upper_used + level * self.m
        if needed > len(self._upper_links):
            bigger = np.full(max(needed, 2 * len(self._upper_links), 64 * self.m), -1, dtype=np.int32)
            bigger[: len(self._upper_links)] = self._upper_links
            self._upper_links = bigger
        self._upper_start[row] = self._upper_used
        self._upper_used = needed

    def _link(self, first: int, size: int) -> None:
        """Adds stored rows to the graph: their links are chosen in parallel
        against the graph as it was before the batch, and then written."""
        from src.vector import kernels

        m = self.m
        levels = [min(int(-math.log(1.0 - self._levels_rng.random()) * self._scale), 30) for _ in range(size)]
        self._levels[first : first + size] = levels
        tallest = max(levels)
        for position, level in enumerate(levels):
            if level:
                self._place_upper(first + position, level)
        kernels.encode(self._vectors, self._codes, self._scales, first, first + size)
        queries, query_scales = _encode_queries(self._vectors[first : first + size])
        out0 = np.full((size, 2 * m), -1, dtype=np.int32)
        out_upper = np.full((size, max(tallest, 1), m), -1, dtype=np.int32)

        def choose(lo: int, hi: int) -> None:
            with self._visited() as marks:
                marks[1] = kernels.choose_links(
                    self._codes, self._scales, queries, query_scales, self._links0, self._upper_start,
                    self._upper_links, m, first, lo, hi, self._levels, self._entry, self._entry_level,
                    self.ef_construction, marks[0], marks[1], out0, out_upper,
                )  # fmt: skip

        _parallel(size, choose, chunk=8)
        for level in range(tallest + 1):
            members = np.array([p for p in range(size) if levels[p] >= level])
            chosen = (out0 if level == 0 else out_upper[:, level - 1])[members]
            self._write_links(first + members, chosen, level)

        self.graph_rows = first + size
        if tallest > self._entry_level:
            self._entry = first + levels.index(tallest)
            self._entry_level = tallest

    def _write_links(self, rows: np.ndarray, chosen: np.ndarray, level: int) -> None:
        from src.vector import kernels

        room = 2 * self.m if level == 0 else self.m
        links = self._links0 if level == 0 else self._upper_links

        def bases(of: np.ndarray) -> np.ndarray:
            return of * room if level == 0 else self._upper_start[of] + (level - 1) * room

        links[(bases(rows)[:, None] + np.arange(room)).ravel()] = chosen.ravel()
        sources, targets = np.repeat(rows, room), chosen.ravel().astype(np.int64)
        keep = targets >= 0
        sources, targets = sources[keep], targets[keep]
        if not len(targets):
            return
        order = np.argsort(targets, kind="stable")
        sources, targets = sources[order].astype(np.int32), targets[order]
        target_bases = bases(targets)
        cuts = np.flatnonzero(np.r_[True, targets[1:] != targets[:-1], True])  # a target is never in two threads

        def link(lo: int, hi: int) -> None:
            kernels.add_back_links(
                self._codes, self._scales, links, target_bases, targets, sources, room, int(cuts[lo]), int(cuts[hi])
            )

        _parallel(len(cuts) - 1, link, chunk=64)

    @contextmanager
    def _visited(self) -> Iterator[list]:
        """[marks, last mark used]: scratch space to know which rows were seen."""
        try:
            marks = self._scratch.get_nowait()
        except Empty:
            marks = [np.zeros(0, dtype=np.int32), 0]
        if len(marks[0]) < len(self._levels):
            marks = [np.zeros(len(self._levels), dtype=np.int32), 0]
        elif marks[1] > 2**31 - 2**24:  # before the marks run out
            marks[0][:] = 0
            marks[1] = 0
        try:
            yield marks
        finally:
            self._scratch.put(marks)

    # --- search ---

    def search(
        self,
        query: np.ndarray,
        k: int,
        *,
        ef: int = DEFAULT_EF,
        allowed: np.ndarray | None = None,
        threshold: float | None = None,
        exact_below: int | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """The best `k` rows, best first, and their similarities. `ef` is the
        search width. A filter that leaves fewer than `exact_below` rows (by
        default, when that is cheaper than the traversal) is scanned."""
        with self._lock.read():
            query = np.ascontiguousarray(query, dtype=np.float32)
            count = self._allowed_count(allowed)
            if exact_below is None:
                exact_below = self._default_exact_below(max(ef, k), 1)
            if count == 0:
                return _NO_ROWS
            if not self.graph_rows or count <= max(exact_below, 0):
                candidates = None if allowed is None else np.flatnonzero(allowed[: self._count])
                rows = np.arange(self._count) if candidates is None else candidates
                sims = self._similarities(candidates, query[None])
            else:
                rows = self._traverse(query, max(ef, k), allowed, _NEVER, 0.0)[0]
                rows = np.concatenate([rows, self._unlinked(allowed)])
                sims = self._similarities(rows, query[None])
            if threshold is not None:
                keep = sims >= threshold
                rows, sims = rows[keep], sims[keep]
            if len(rows) > k:
                cut = np.partition(sims, len(sims) - k)[len(sims) - k]
                keep = sims >= cut
                rows, sims = rows[keep], sims[keep]
            order = np.lexsort((rows, -sims))[:k]
            return rows[order].astype(np.int64), sims[order]

    def search_threshold(
        self,
        queries: np.ndarray,
        threshold: float,
        *,
        ef: int = DEFAULT_EF,
        slack: float = DEFAULT_SLACK,
        upper_ef: int = DEFAULT_UPPER_EF,
        allowed: np.ndarray | None = None,
        exact_below: int | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Every row whose best similarity to any of the queries reaches the
        threshold, in row order, and that similarity. The traversal goes on
        through rows up to `slack` below the threshold, to reach others behind."""
        with self._lock.read():
            queries = np.ascontiguousarray(queries, dtype=np.float32)
            count = self._allowed_count(allowed)
            if exact_below is None:
                exact_below = self._default_exact_below(ef, len(queries))
            if count == 0 or len(queries) == 0:
                return _NO_ROWS
            if not self.graph_rows or count <= max(exact_below, 0):
                candidates = None if allowed is None else np.flatnonzero(allowed[: self._count])
                rows = np.arange(self._count) if candidates is None else candidates
                sims = self._similarities(candidates, queries)
            else:
                found = _map(lambda q: self._traverse(q, ef, allowed, np.float32(threshold - CODE_ERROR), slack, upper_ef)[1], list(queries))
                rows = np.unique(np.concatenate([*found, self._unlinked(allowed)]))
                sims = self._similarities(rows, queries)
            keep = sims >= threshold
            return rows[keep].astype(np.int64), sims[keep]

    def _allowed_count(self, allowed: np.ndarray | None) -> int:
        if allowed is None:
            return self._count
        if len(allowed) < self._count:
            raise ValueError("the mask must cover every row")
        return int(np.count_nonzero(allowed[: self._count]))

    def _default_exact_below(self, ef: int, queries: int) -> int:
        """Where both ways cost about the same. The traversal computes some 16
        similarities per step and needs more steps the fewer rows are allowed;
        the scan reads each row once, and further queries add little to that."""
        traversal = 16 * ef * self._count * queries / (1 + 0.1 * (queries - 1))
        return max(MIN_EXACT, int(math.sqrt(traversal)))

    def _similarities(self, rows: np.ndarray | None, queries: np.ndarray) -> np.ndarray:
        """The best similarity of each row (all, if None) to the queries."""
        total = self._count if rows is None else len(rows)
        out = np.empty(total, dtype=np.float32)

        if rows is not None and self.graph_rows:
            from src.vector import kernels

            def scan(lo: int, hi: int) -> None:  # does not copy the rows
                kernels.scan_best(self._vectors, rows[lo:hi], queries, out[lo:hi])

            _parallel(total, scan, chunk=max(64, SCAN_BLOCK // len(queries)))
            return out

        def multiply(lo: int, hi: int) -> None:
            vectors = self._vectors[lo:hi] if rows is None else self._vectors[rows[lo:hi]]
            sims = vectors @ queries.T
            out[lo:hi] = sims[:, 0] if len(queries) == 1 else sims.max(axis=1)

        _parallel(total, multiply, chunk=SCAN_BLOCK)
        return out

    def _unlinked(self, allowed: np.ndarray | None) -> np.ndarray:
        """The rows that are stored and not in the graph yet."""
        late = np.arange(self.graph_rows, self._count, dtype=np.int64)
        return late if allowed is None else late[allowed[late] != 0]

    def _traverse(self, query: np.ndarray, ef: int, allowed, threshold, slack: float, upper_ef: int = 0):
        """The best `ef` rows, and the ones that reach the threshold, by their codes."""
        from src.vector import kernels

        queries, scales = _encode_queries(query[None])
        code, scale = queries[0], scales[0]
        with self._visited() as marks:
            stop = 1 if upper_ef and self._entry_level > 0 else 0
            entry = kernels.descend(
                self._codes, self._scales, self._upper_start, self._upper_links, self.m, code, self._entry,
                self._entry_level, stop,
            )  # fmt: skip
            entries = np.array([entry], dtype=np.int32)
            if stop:
                marks[1] += 1
                rows, sims, over, _, _ = kernels.search_layer(
                    self._codes, self._scales, self._upper_links, self._upper_start, 1, self.m, code, scale, entries,
                    upper_ef, marks[0], marks[1], _NO_FILTER, False, np.float32(threshold - SEED_SLACK),
                    np.float32(0.0),
                )  # fmt: skip
                entries = over if len(over) else rows[[sims.argmax()]]
            marks[1] += 1
            rows, _, over, _, computed = kernels.search_layer(
                self._codes, self._scales, self._links0, self._upper_start, 0, 2 * self.m, code, scale, entries, ef,
                marks[0], marks[1], _NO_FILTER if allowed is None else allowed, allowed is not None,
                np.float32(threshold), np.float32(slack),
            )  # fmt: skip
        return rows, over, computed


def _encode_queries(vectors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from src.vector.kernels import QUERY_LEVELS

    scales = np.abs(vectors).max(axis=1) / QUERY_LEVELS
    codes = np.round(vectors / np.where(scales == 0, 1, scales)[:, None]).astype(np.int16)
    return codes, scales.astype(np.float32)


def _parallel(size: int, work: Callable[[int, int], None], *, chunk: int) -> None:
    """Runs `work(lo, hi)` over the range in pieces, in this thread if it is one piece."""
    if size <= chunk or THREADS == 1:
        for lo in range(0, size, chunk):
            work(lo, min(lo + chunk, size))
        return
    for future in [_pool.submit(work, lo, min(lo + chunk, size)) for lo in range(0, size, chunk)]:
        future.result()


def _map(function: Callable, items: list) -> list:
    return list(_pool.map(function, items)) if len(items) > 1 else [function(items[0])]
