"""Embeddings with no model, no network and no GPU.

Words and word pairs are hashed to fixed pseudo-random directions and added up.
Texts that share vocabulary end up close and texts that share none are almost
orthogonal. An optional synonym table adds one common feature to phrases that
mean the same, so that paraphrases are close without sharing words.

All sums are done on integers, and only the final division and square root are
floating point, which IEEE 754 rounds exactly: the same text and seed give the
same vector on every machine."""
from __future__ import annotations

import hashlib
import json
import math
import struct
import threading
from collections.abc import Mapping, Sequence

import numpy as np

from src.processor.embeddings import EMBEDDING_DIM
from src.text.tokens import content_tokens

# Bump it when the vector for a text changes: stored vectors stop being comparable.
ALGORITHM_VERSION = 1

MIN_DIM = 16
NONZEROS = 8  # signed entries per feature direction
BATCH = 256  # larger batches leave the processor cache and are slower
WEIGHT_SCALE = 1024  # weights are integers in units of 1/1024

WORD_WEIGHT = 1.0
NUMBER_WEIGHT = 0.25  # dates, file numbers and amounts say little about the topic
PAIR_WEIGHT = 0.5
CONCEPT_WEIGHT = 3.0

_EMPTY_FEATURE = "empty:"


class HashedEmbeddingProvider:
    def __init__(
        self,
        *,
        dim: int = EMBEDDING_DIM,
        seed: int = 0,
        synonyms: Mapping[str, Sequence[str]] | None = None,
        cache_size: int = 400_000,
    ) -> None:
        if dim < MIN_DIM:
            raise ValueError(f"dim must be at least {MIN_DIM}")
        self._dim = dim
        self._seed = seed
        self._cache_size = cache_size
        self._lock = threading.Lock()  # the API embeds from several threads
        # Feature -> row of the direction table. Cleared when it grows too much.
        self._rows: dict[str, int] = {}
        self._positions = np.empty((1024, NONZEROS), dtype=np.int64)
        self._signs = np.empty((1024, NONZEROS), dtype=np.float64)
        self._phrases, self._phrase_lengths = self._index_synonyms(synonyms or {})

    @staticmethod
    def _index_synonyms(
        synonyms: Mapping[str, Sequence[str]],
    ) -> tuple[dict[tuple[str, ...], str], dict[str, list[int]]]:
        phrases: dict[tuple[str, ...], str] = {}
        for concept, variants in synonyms.items():
            for variant in variants:
                key = tuple(content_tokens(variant))
                if not key:
                    continue
                if phrases.setdefault(key, concept) != concept:
                    raise ValueError(f"the phrase {variant!r} belongs to both {phrases[key]!r} and {concept!r}")
        # First word -> lengths of the phrases that start with it, longest first.
        lengths: dict[str, set[int]] = {}
        for key in phrases:
            lengths.setdefault(key[0], set()).add(len(key))
        return phrases, {word: sorted(sizes, reverse=True) for word, sizes in lengths.items()}

    def _row(self, feature: str) -> int:
        row = self._rows.get(feature)
        if row is None:
            row = len(self._rows)
            if row == len(self._positions):
                self._positions = np.concatenate([self._positions, np.empty_like(self._positions)])
                self._signs = np.concatenate([self._signs, np.empty_like(self._signs)])
            digest = hashlib.blake2b(f"{self._seed}:{feature}".encode(), digest_size=4 * NONZEROS).digest()
            values = struct.unpack(f"<{NONZEROS}I", digest)
            self._positions[row] = [(v >> 1) % self._dim for v in values]
            self._signs[row] = [1 if v & 1 else -1 for v in values]
            self._rows[feature] = row
        return row

    def _features(self, text: str) -> dict[str, float]:
        """Feature -> weight before the square root of its count is applied."""
        words = content_tokens(text)
        if not words:
            return {_EMPTY_FEATURE: 1.0}
        counts: dict[str, int] = {}
        for word in words:
            counts[word] = counts.get(word, 0) + 1
        weighted = {
            word: (NUMBER_WEIGHT if word[0].isdigit() else WORD_WEIGHT) * math.sqrt(count)
            for word, count in counts.items()
        }
        pairs: dict[str, int] = {}
        for first, second in zip(words, words[1:], strict=False):
            pair = f"{first} {second}"
            pairs[pair] = pairs.get(pair, 0) + 1
        for pair, count in pairs.items():
            weighted[pair] = PAIR_WEIGHT * math.sqrt(count)
        if self._phrases:
            concepts: dict[str, int] = {}
            for position, word in enumerate(words):
                for length in self._phrase_lengths.get(word, ()):
                    concept = self._phrases.get(tuple(words[position : position + length]))
                    if concept is not None:
                        concepts[concept] = concepts.get(concept, 0) + 1
                        break
            for concept, count in concepts.items():
                weighted[f"concept:{concept}"] = CONCEPT_WEIGHT * math.sqrt(count)
        return weighted

    def embed_passages(self, texts: Sequence[str]) -> np.ndarray:
        """One unit vector per row."""
        blocks = []
        for start in range(0, len(texts), BATCH):
            with self._lock:
                blocks.append(self._embed(texts[start : start + BATCH]))
        return np.concatenate(blocks) if blocks else np.empty((0, self._dim), dtype=np.float32)

    def _embed(self, texts: Sequence[str]) -> np.ndarray:
        if len(self._rows) > self._cache_size:
            self._rows.clear()
        rows: list[int] = []
        weights: list[int] = []
        sizes: list[int] = []
        for text in texts:
            features = self._features(text)
            rows.extend(map(self._row, features))
            weights.extend(round(w * WEIGHT_SCALE) for w in features.values())
            sizes.append(len(features))
        owner = np.repeat(np.arange(len(texts)), sizes)
        index = np.array(rows, dtype=np.int64)
        cells = (owner[:, None] * self._dim + self._positions[index]).ravel()
        values = (self._signs[index] * np.array(weights, dtype=np.float64)[:, None]).ravel()
        # Whole numbers far below 2**53: the sums are exact in any order.
        totals = np.bincount(cells, weights=values, minlength=len(texts) * self._dim).reshape(len(texts), self._dim)
        whole = totals.astype(np.int64)
        squares = np.einsum("ij,ij->i", whole, whole)
        for position in np.flatnonzero(squares == 0):  # every entry cancelled out
            whole[position, 0] = 1
            squares[position] = 1
        norms = np.array([math.sqrt(s) for s in squares.tolist()])
        return (whole / norms[:, None]).astype(np.float32)

    def embed_passage(self, texto: str) -> list[float]:
        return self.embed_passages([texto])[0].tolist()

    def embed_query(self, texto: str) -> list[float]:
        return self.embed_passage(texto)

    def describe(self) -> dict:
        table = json.dumps(sorted((list(k), v) for k, v in self._phrases.items()))
        return {
            "provider": "hashed",
            "version": ALGORITHM_VERSION,
            "dim": self._dim,
            "seed": self._seed,
            "synonym_phrases": len(self._phrases),
            "synonyms_sha256": hashlib.sha256(table.encode()).hexdigest()[:16] if self._phrases else None,
        }
