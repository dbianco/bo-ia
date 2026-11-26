"""In-process search engine over fragments: a lexical index, a vector index and
metadata filters, with the two rankings fused.

Rows are fragments, numbered alike in the three indexes. A document that changes
gets new rows, and the old ones are left unused until there are too many."""
from __future__ import annotations

import datetime
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from src.config.installation import Filtro
from src.engine.lexical import LexicalIndex
from src.engine.metadata import MetadataIndex, resolve
from src.processor.hybrid import fusionar_rrf
from src.vector.hnsw import GRAPH_FROM, VectorIndex
from src.vector.locks import ReadWriteLock

# As in the PostgreSQL implementation: how many candidates of each kind are fused.
MIN_CANDIDATES = 50
OVERSAMPLING = 5

DEFAULT_EF = 128
_ROW_ARRAYS = ("_fragment_ids", "_document_ids", "_text_hashes", "_has_vector")
MODES = ("semantic", "hybrid", "all", "lexical")


@dataclass
class EngineFragment:
    fragment_id: int
    text: str
    vector: Sequence[float] | np.ndarray | None


@dataclass(frozen=True)
class Hit:
    fragment_id: int
    document_id: int
    similarity: float
    text_match: bool


@dataclass(frozen=True)
class StoredFragment:
    fragment_id: int
    text_hash: int
    vector: np.ndarray | None  # unit length


@dataclass
class _Document:
    first: int
    count: int


class SearchEngine:
    def __init__(
        self,
        dim: int,
        *,
        fusion_weights: tuple[float, float] = (1.0, 1.0),
        ef: int = DEFAULT_EF,
        graph_from: int = GRAPH_FROM,
        compact_from: int = 20_000,
        capacity: int = 1024,
    ) -> None:
        self._dim = dim
        self._weights = fusion_weights  # of the vector ranking and of the text one
        self._ef = ef
        self._graph_from = graph_from
        self._compact_from = compact_from
        self._lock = ReadWriteLock()
        self._start(capacity)

    def _start(self, capacity: int) -> None:
        self._lexical = LexicalIndex()
        self._metadata = MetadataIndex()
        self._vectors = VectorIndex(self._dim, graph_from=self._graph_from, capacity=capacity)
        self._documents: dict[int, _Document] = {}
        self._fragment_ids = np.zeros(max(capacity, 16), dtype=np.int64)
        self._document_ids = np.zeros(max(capacity, 16), dtype=np.int64)
        self._text_hashes = np.zeros(max(capacity, 16), dtype=np.int64)  # to know if a text changed
        self._has_vector = np.zeros(max(capacity, 16), dtype=np.uint8)
        self._without_vector = 0

    def __len__(self) -> int:
        """Documents."""
        return len(self._documents)

    def __contains__(self, document_id: int) -> bool:
        return document_id in self._documents

    @property
    def rows(self) -> int:
        return len(self._vectors)

    @property
    def vectors(self) -> VectorIndex:
        return self._vectors

    @property
    def lexical(self) -> LexicalIndex:
        return self._lexical

    # --- changes ---

    def put(
        self, document_id: int, date: datetime.date, metadata: dict, fragments: Sequence[EngineFragment]
    ) -> None:
        """Adds a document, or replaces it."""
        self.put_many([(document_id, date, metadata, fragments)])

    def put_many(
        self, documents: Iterable[tuple[int, datetime.date, dict, Sequence[EngineFragment]]]
    ) -> None:
        documents = list(documents)
        fragments = [f for _, _, _, own in documents for f in own]
        matrix = np.zeros((len(fragments), self._dim), dtype=np.float32)
        for row, fragment in enumerate(fragments):
            if fragment.vector is not None:
                matrix[row] = fragment.vector
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix /= np.where(norms == 0, 1, norms)
        with self._lock.write():
            for document_id, _, _, _ in documents:
                self._forget(document_id)
            first = self.rows
            self._grow(first + len(fragments))
            for row, fragment in enumerate(fragments, start=first):
                self._fragment_ids[row] = fragment.fragment_id
                self._text_hashes[row] = hash(fragment.text)
                self._has_vector[row] = fragment.vector is not None
            self._without_vector += sum(1 for f in fragments if f.vector is None)
            row = first
            for document_id, date, metadata, own in documents:
                self._document_ids[row : row + len(own)] = document_id
                if own:
                    self._metadata.add(metadata, date.toordinal(), len(own))
                self._documents[document_id] = _Document(row, len(own))
                row += len(own)
            if fragments:
                self._lexical.add([f.text for f in fragments])
                self._vectors.add(matrix)
            self._compact_if_needed()

    def update(self, document_id: int, date: datetime.date, metadata: dict) -> bool:
        """Changes what is not the text. Returns whether anything changed."""
        with self._lock.write():
            document = self._documents[document_id]
            if not document.count or self._metadata.of(document.first) == (metadata, date.toordinal()):
                return False
            self._metadata.update(document.first, document.count, metadata, date.toordinal())
            return True

    def remove(self, document_id: int) -> None:
        with self._lock.write():
            self._forget(document_id)
            self._compact_if_needed()

    def fragments_of(self, document_id: int) -> list[StoredFragment]:
        with self._lock.read():
            document = self._documents[document_id]
            return [
                StoredFragment(
                    int(self._fragment_ids[row]),
                    int(self._text_hashes[row]),
                    self._vectors.vectors[row] if self._has_vector[row] else None,
                )
                for row in range(document.first, document.first + document.count)
            ]

    def _forget(self, document_id: int) -> None:
        document = self._documents.pop(document_id, None)
        if document is not None and document.count:
            self._metadata.remove(document.first, document.count)

    def _grow(self, total: int) -> None:
        if total > len(self._fragment_ids):
            size = max(total, 2 * len(self._fragment_ids))
            for name in _ROW_ARRAYS:
                old = getattr(self, name)
                setattr(self, name, np.concatenate([old, np.zeros(size - len(old), dtype=old.dtype)]))

    def _compact_if_needed(self) -> None:
        used = sum(d.count for d in self._documents.values()) if self.rows >= self._compact_from else self.rows
        if self.rows - used < self._compact_from or (self.rows - used) * 2 <= self.rows:
            return
        kept = sorted(self._documents.items(), key=lambda item: item[1].first)
        rows = np.concatenate(
            [np.arange(d.first, d.first + d.count) for _, d in kept] or [np.empty(0, dtype=np.int64)]
        ).astype(np.int64)
        old = (self._lexical, self._metadata, self._vectors)
        arrays = {name: getattr(self, name)[rows] for name in _ROW_ARRAYS}
        self._start(len(rows))
        self._grow(len(rows))
        for name, values in arrays.items():
            getattr(self, name)[: len(rows)] = values
        self._without_vector = int(len(rows) - arrays["_has_vector"].sum())
        row = 0
        for document_id, document in kept:
            if document.count:
                metadata, day = old[1].of(document.first)
                self._metadata.add(metadata, day, document.count)
            self._documents[document_id] = _Document(row, document.count)
            row += document.count
        self._lexical = old[0].keeping(rows)
        self._vectors.add(old[2].vectors[rows])

    # --- search ---

    def search(
        self,
        text: str,
        vector: Sequence[float] | np.ndarray,
        *,
        mode: str,
        limit: int,
        threshold: float,
        filters: Mapping[str, str] | None = None,
        filters_declared: Sequence[Filtro] = (),
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
    ) -> list[Hit]:
        """`semantic`: the nearest fragments that reach the threshold. `hybrid`:
        those and the ones with every word of the query, fused. `all`: the same
        without threshold. `lexical`: BM25, any word (for comparison)."""
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}")
        conditions = resolve(filters or {}, filters_declared)
        query = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(query)
        query = query / norm if norm else query
        with self._lock.read():
            if not self.rows:
                return []
            mask = self._metadata.mask(
                conditions,
                date_from=date_from.toordinal() if date_from else None,
                date_to=date_to.toordinal() if date_to else None,
            )
            if mode == "lexical":
                rows, _ = self._lexical.search(text, limit, allowed=mask)
                return self._hits(rows.tolist(), {}, set(rows.tolist()), query)
            if mode == "semantic":
                rows, sims = self._nearest(query, limit, mask, threshold)
                return self._hits(rows.tolist(), dict(zip(rows.tolist(), sims.tolist(), strict=True)), set(), query)

            candidates = max(limit * OVERSAMPLING, MIN_CANDIDATES)
            by_text = self._lexical.search(text, candidates, allowed=mask, require_all=True)[0].tolist()
            # Without text matches, nothing below the threshold can be in a hybrid
            # result; with them, its place in the vector ranking counts.
            floor = None if mode == "all" or by_text else threshold
            rows, sims = self._nearest(query, candidates, mask, floor)
            similarity = dict(zip(rows.tolist(), sims.tolist(), strict=True))
            in_text = set(by_text)
            scores = fusionar_rrf(rows.tolist(), by_text, pesos=self._weights)
            ranked = sorted(scores, key=lambda row: -scores[row])
            if mode == "hybrid":
                ranked = [row for row in ranked if row in in_text or similarity[row] >= threshold]
            return self._hits(ranked[:limit], similarity, in_text, query)

    def warm_up(self) -> None:
        """Compiles what a search needs, so that the first user does not wait."""
        index = LexicalIndex()
        index.add(["puente"])
        index.search("puente", 1)

    def _nearest(self, query: np.ndarray, k: int, mask: np.ndarray | None, threshold: float | None):
        if self._without_vector:
            with_vector = self._has_vector[: self.rows]
            mask = with_vector if mask is None else mask & with_vector
        return self._vectors.search(query, k, ef=max(self._ef, k), allowed=mask, threshold=threshold)

    def _hits(self, rows: list[int], similarity: dict[int, float], in_text: set[int], query: np.ndarray) -> list[Hit]:
        return [
            Hit(
                fragment_id=int(self._fragment_ids[row]),
                document_id=int(self._document_ids[row]),
                # A text match outside the vector candidates: its similarity is computed.
                similarity=similarity[row] if row in similarity else float(self._vectors.vectors[row] @ query),
                text_match=row in in_text,
            )
            for row in rows
        ]
