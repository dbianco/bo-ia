"""Implementations the harness can measure, starting with the references. A
search system has `search(query, filters, k)` and returns document identifiers,
best first. A match system has `match(document)` and returns subscription ids."""
from __future__ import annotations

import math
from array import array
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Protocol

import numpy as np

from src.config.installation import Filtro
from src.engine.engine import EngineFragment, SearchEngine
from src.ingestor.contract import DocumentoNormalizado
from src.ingestor.fragmenter import fragmentar_texto
from src.matching.subscription_index import SubscriptionIndex
from src.processor.embeddings import EmbeddingProvider
from src.search.filters import construir_filtros_suscripcion, cumple_filtros
from src.synthetic.corpus import Subscription, Truth
from src.text.tokens import content_tokens

# Scores are compared after rounding, and ties go by identifier, so that the
# last bit of a floating point sum cannot reorder results between machines.
SCORE_DECIMALS = 5
EMBED_BATCH = 256
EMBED_DOCUMENTS = 20_000


class SearchSystem(Protocol):
    name: str

    def search(self, query: str, filters: dict[str, str], k: int) -> list[str]: ...


class MatchSystem(Protocol):
    name: str

    def match(self, document: DocumentoNormalizado) -> set[str]: ...


class OracleSearch:
    """Reads the truth: the ceiling for any other system."""

    name = "oracle"

    def __init__(self, truth: Truth) -> None:
        self._answers = {
            (q.text, tuple(sorted(q.filters.items()))): [i for i, _ in sorted(q.relevant.items(), key=lambda x: -x[1])]
            for q in truth.queries
        }

    def search(self, query: str, filters: dict[str, str], k: int) -> list[str]:
        return self._answers[(query, tuple(sorted(filters.items())))][:k]


class OracleMatch:
    name = "oracle"

    def __init__(self, truth: Truth) -> None:
        self._answers: dict[str, set[str]] = {}
        for subscription in truth.subscriptions:
            for identifier in subscription.must_match:
                self._answers.setdefault(identifier, set()).add(subscription.id)

    def match(self, document: DocumentoNormalizado) -> set[str]:
        return self._answers.get(document.identificador_externo, set())


class _FilterMask:
    """Which documents satisfy a filter, by the same rule the engine uses."""

    def __init__(self, documents: Sequence[DocumentoNormalizado], filters: Sequence[Filtro]) -> None:
        self._metadata = [d.metadata for d in documents]
        self._declared = list(filters)

    def allowed(self, filters: dict[str, str]) -> np.ndarray | None:
        if not filters:
            return None
        snapshot = construir_filtros_suscripcion(filters, self._declared)
        return np.fromiter((cumple_filtros(m, snapshot) for m in self._metadata), dtype=bool, count=len(self._metadata))


def _ranked(ids: Sequence[str], scores: np.ndarray, candidates: np.ndarray, k: int) -> list[tuple[str, float]]:
    rounded = np.round(scores[candidates], SCORE_DECIMALS)
    if len(candidates) > k:
        # Keep everything tied with the k-th score, then break ties by identifier.
        cut = np.partition(rounded, len(rounded) - k)[len(rounded) - k]
        keep = rounded >= cut
        candidates, rounded = candidates[keep], rounded[keep]
    best = sorted(zip(candidates.tolist(), rounded.tolist(), strict=True), key=lambda x: (-x[1], ids[x[0]]))[:k]
    return [(ids[i], float(scores[i])) for i, _ in best]


class LexicalSearch:
    """BM25 over whole documents: a baseline that only sees shared words."""

    name = "lexical-bm25"
    K1 = 1.2
    B = 0.75

    def __init__(self, documents: Sequence[DocumentoNormalizado], filters: Sequence[Filtro]) -> None:
        self._ids = [d.identificador_externo for d in documents]
        self._mask = _FilterMask(documents, filters)
        postings: dict[str, tuple[array, array]] = {}
        lengths = np.zeros(len(documents), dtype=np.float64)
        for position, document in enumerate(documents):
            words = content_tokens(document.texto)
            lengths[position] = len(words)
            for word, count in Counter(words).items():
                where, counts = postings.setdefault(word, (array("I"), array("H")))
                where.append(position)
                counts.append(min(count, 65535))
        self._postings = postings
        self._norm = self.K1 * (1 - self.B + self.B * lengths / lengths.mean())

    def scored(self, query: str, filters: dict[str, str], k: int) -> list[tuple[str, float]]:
        total = len(self._ids)
        scores = np.zeros(total)
        for word in dict.fromkeys(content_tokens(query)):
            if word not in self._postings:
                continue
            where, counts = self._postings[word]
            at = np.frombuffer(where, dtype=np.uint32)
            tf = np.frombuffer(counts, dtype=np.uint16).astype(np.float64)
            idf = math.log(1 + (total - len(at) + 0.5) / (len(at) + 0.5))
            scores[at] += idf * tf * (self.K1 + 1) / (tf + self._norm[at])
        found = scores > 0
        allowed = self._mask.allowed(filters)
        if allowed is not None:
            found &= allowed
        return _ranked(self._ids, scores, np.flatnonzero(found), k)

    def search(self, query: str, filters: dict[str, str], k: int) -> list[str]:
        return [identifier for identifier, _ in self.scored(query, filters, k)]


def embed_passages(provider: EmbeddingProvider, texts: Sequence[str]) -> np.ndarray:
    """Unit vectors as rows, using the provider's batch method when it has one."""
    batch = getattr(provider, "embed_passages", None)
    matrix = batch(texts) if batch else np.array([provider.embed_passage(t) for t in texts], dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return (matrix / np.where(norms == 0, 1, norms)).astype(np.float32)


def embed_query(provider: EmbeddingProvider, text: str) -> np.ndarray:
    vector = np.array(provider.embed_query(text), dtype=np.float32)
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


def _fragments(documents: Iterable[DocumentoNormalizado]) -> Iterable[tuple[int, str]]:
    for position, document in enumerate(documents):
        for text in fragmentar_texto(document.texto):
            yield position, text


class VectorExactSearch:
    """Exact cosine scan. A document scores as its best fragment. Any
    approximate index is measured against this one."""

    name = "vector-exact"

    def __init__(
        self, documents: Sequence[DocumentoNormalizado], provider: EmbeddingProvider, filters: Sequence[Filtro]
    ) -> None:
        self._ids = [d.identificador_externo for d in documents]
        self._mask = _FilterMask(documents, filters)
        self._provider = provider
        owners: list[int] = []
        blocks: list[np.ndarray] = []
        pending: list[str] = []
        for position, text in _fragments(documents):
            owners.append(position)
            pending.append(text)
            if len(pending) == EMBED_BATCH:
                blocks.append(embed_passages(provider, pending))
                pending = []
        if pending:
            blocks.append(embed_passages(provider, pending))
        self._blocks = blocks
        # Fragments of a document are contiguous, so each document is a slice.
        owner_array = np.array(owners)
        self._starts = np.flatnonzero(np.r_[True, owner_array[1:] != owner_array[:-1]])
        self.fragments = len(owners)

    def scores(self, query: str) -> np.ndarray:
        vector = embed_query(self._provider, query)
        similarity = np.concatenate([block @ vector for block in self._blocks])
        return np.maximum.reduceat(similarity, self._starts)

    def search(self, query: str, filters: dict[str, str], k: int) -> list[str]:
        allowed = self._mask.allowed(filters)
        candidates = np.arange(len(self._ids)) if allowed is None else np.flatnonzero(allowed)
        return [identifier for identifier, _ in _ranked(self._ids, self.scores(query), candidates, k)]

    def neighbours(self, positions: Sequence[int], k: int) -> list[list[int]]:
        """Nearest other documents of each document, by its first fragment."""
        matrix = np.concatenate(self._blocks)
        result = []
        for position in positions:
            similarity = np.maximum.reduceat(matrix @ matrix[self._starts[position]], self._starts)
            similarity[position] = -np.inf
            order = np.lexsort((np.arange(len(similarity)), -np.round(similarity, SCORE_DECIMALS)))
            result.append(order[:k].tolist())
        return result


class EngineSearch:
    """The search engine of plan 4, in this process. Documents, not fragments:
    each one counts once, as its best fragment."""

    FRAGMENTS_PER_DOCUMENT = 4

    def __init__(
        self, engine: SearchEngine, ids: Sequence[str], provider: EmbeddingProvider, filters: Sequence[Filtro],
        mode: str, threshold: float,
    ) -> None:  # fmt: skip
        self.name = f"engine-{mode}"
        self.engine = engine
        self._ids = ids
        self._provider = provider
        self._filters = filters
        self._mode = mode
        self._threshold = threshold

    @classmethod
    def build(
        cls, documents: Sequence[DocumentoNormalizado], provider: EmbeddingProvider, filters: Sequence[Filtro], **options
    ) -> EngineSearch:
        """Use `with_mode` on the result for each mode: the engine is shared."""
        engine: SearchEngine | None = None
        fragment_id = 0
        for start in range(0, len(documents), EMBED_DOCUMENTS):
            chunk = documents[start : start + EMBED_DOCUMENTS]
            texts = [fragmentar_texto(d.texto) for d in chunk]
            matrix = embed_passages(provider, [t for own in texts for t in own])
            engine = engine or SearchEngine(matrix.shape[1], **options)
            vectors = iter(matrix)
            batch = []
            for position, (document, own) in enumerate(zip(chunk, texts, strict=True), start=start):
                fragments = []
                for text in own:
                    fragments.append(EngineFragment(fragment_id, text, next(vectors)))
                    fragment_id += 1
                batch.append((position, document.fecha, document.metadata, fragments))
            engine.put_many(batch)
        return cls(engine, [d.identificador_externo for d in documents], provider, filters, "semantic", 0.0)

    def with_mode(self, mode: str, *, threshold: float) -> EngineSearch:
        return EngineSearch(self.engine, self._ids, self._provider, self._filters, mode, threshold)

    def search(self, query: str, filters: dict[str, str], k: int) -> list[str]:
        hits = self.engine.search(
            query,
            embed_query(self._provider, query),
            mode=self._mode,
            limit=k * self.FRAGMENTS_PER_DOCUMENT,
            threshold=self._threshold,
            filters=filters,
            filters_declared=self._filters,
        )
        return list(dict.fromkeys(self._ids[h.document_id] for h in hits))[:k]


class IndexedMatch:
    """The matching engine of plan 3, in this process."""

    name = "match-indexed"

    def __init__(
        self,
        subscriptions: Sequence[Subscription],
        provider: EmbeddingProvider,
        filters: Sequence[Filtro],
        *,
        threshold: float,
    ) -> None:
        self._provider = provider
        self._threshold = threshold
        self._identifiers = [s.id for s in subscriptions]
        vectors = [embed_query(provider, s.text) for s in subscriptions]
        self._index = SubscriptionIndex(len(vectors[0]))
        self._index.add_many(
            (i, vector, construir_filtros_suscripcion(s.filters, list(filters)), True)
            for i, (s, vector) in enumerate(zip(subscriptions, vectors, strict=True))
        )

    def match(self, document: DocumentoNormalizado) -> set[str]:
        fragments = embed_passages(self._provider, fragmentar_texto(document.texto))
        return {self._identifiers[i] for i in self._index.match(document.metadata, fragments, self._threshold)}


class BruteForceMatch:
    """Compares a document with every subscription, one by one."""

    name = "match-brute-force"

    def __init__(
        self,
        subscriptions: Sequence[Subscription],
        provider: EmbeddingProvider,
        filters: Sequence[Filtro],
        *,
        threshold: float,
    ) -> None:
        self._provider = provider
        self._threshold = threshold
        self._subscriptions = [
            (s.id, embed_query(provider, s.text), construir_filtros_suscripcion(s.filters, list(filters)))
            for s in subscriptions
        ]

    def match(self, document: DocumentoNormalizado) -> set[str]:
        fragments = embed_passages(self._provider, fragmentar_texto(document.texto))
        matched = set()
        for identifier, vector, snapshot in self._subscriptions:
            if not cumple_filtros(document.metadata, snapshot):
                continue
            if round(float((fragments @ vector).max()), SCORE_DECIMALS) >= self._threshold:
                matched.add(identifier)
        return matched
