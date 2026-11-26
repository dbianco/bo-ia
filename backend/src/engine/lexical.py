"""Inverted index with BM25 scores, and top-k retrieval that does not score the
documents that cannot enter the result.

Rows are added in order and never change. They live in segments of consecutive
rows; small segments are merged as they pile up. Statistics (how many rows have
a term, average length) are of the whole index and always current, so the result
does not depend on how the rows arrived."""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from src.engine.analyzer import analyze

K1 = 1.2
B = 0.75
BLOCK = 128  # postings per block, each with its bounds
MAX_SEGMENT = 100_000  # rows; segments this large are not merged any more

_NOTHING = np.empty(0, dtype=np.int64), np.empty(0)


@dataclass
class _Segment:
    base: int  # first row
    rows: int
    terms: np.ndarray  # sorted identifiers of the terms that appear
    offsets: np.ndarray  # where the postings of each term start, and the end
    docs: np.ndarray  # row within the segment
    tfs: np.ndarray
    block_offsets: np.ndarray
    block_last: np.ndarray
    block_tf: np.ndarray  # the largest count of the block and the shortest row:
    block_len: np.ndarray  # together, a bound that holds for any average length
    term_tf: np.ndarray
    term_len: np.ndarray


def _make_segment(base: int, rows: int, terms: np.ndarray, docs: np.ndarray, tfs: np.ndarray, lengths: np.ndarray):
    """From postings in row order."""
    order = np.argsort(terms, kind="stable")
    terms, docs, tfs = terms[order], docs[order], tfs[order]
    starts = np.flatnonzero(np.r_[True, terms[1:] != terms[:-1]]) if len(terms) else np.empty(0, dtype=np.int64)
    offsets = np.r_[starts, len(terms)].astype(np.int64)
    blocks = -(-np.diff(offsets) // BLOCK)
    block_offsets = np.r_[0, np.cumsum(blocks)].astype(np.int64)
    total = int(block_offsets[-1])
    block_starts = np.repeat(offsets[:-1], blocks) + BLOCK * (np.arange(total) - np.repeat(block_offsets[:-1], blocks))
    own = lengths[base + docs] if len(docs) else np.empty(0, dtype=np.int32)
    if total:
        block_tf = np.maximum.reduceat(tfs, block_starts)
        block_len = np.minimum.reduceat(own, block_starts)
        block_ends = np.r_[block_starts[1:], len(docs)]
        # A block ends where the next one of the same term starts, or with the term.
        block_last = docs[block_ends - 1]
        term_tf = np.maximum.reduceat(block_tf, block_offsets[:-1])
        term_len = np.minimum.reduceat(block_len, block_offsets[:-1])
    else:
        block_tf, block_len, block_last = tfs[:0], own[:0], docs[:0]
        term_tf, term_len = tfs[:0], own[:0]
    return _Segment(
        base, rows, terms[starts], offsets, docs, tfs, block_offsets, block_last, block_tf, block_len, term_tf, term_len
    )


class LexicalIndex:
    def __init__(self) -> None:
        self._vocabulary: dict[str, int] = {}
        self._frequency = np.zeros(1024, dtype=np.int64)  # rows with each term
        self._lengths = np.zeros(1024, dtype=np.int32)
        self._total_length = 0
        self._rows = 0
        self._segments: list[_Segment] = []
        self.last_scored = 0  # rows scored by the last search: for tests and benchmarks

    def __len__(self) -> int:
        return self._rows

    @property
    def segments(self) -> int:
        return len(self._segments)

    def add(self, texts: Sequence[str]) -> range:
        first = self._rows
        for start in range(0, len(texts), MAX_SEGMENT):
            self._add_segment(texts[start : start + MAX_SEGMENT])
        return range(first, self._rows)

    def _add_segment(self, texts: Sequence[str]) -> None:
        base, count = self._rows, len(texts)
        if base + count > len(self._lengths):
            bigger = np.zeros(max(base + count, 2 * len(self._lengths)), dtype=np.int32)
            bigger[:base] = self._lengths[:base]
            self._lengths = bigger
        terms: list[int] = []
        docs: list[int] = []
        tfs: list[int] = []
        vocabulary = self._vocabulary
        for row, text in enumerate(texts):
            words = analyze(text)
            self._lengths[base + row] = len(words)
            counts = Counter(words)
            terms.extend(vocabulary.setdefault(word, len(vocabulary)) for word in counts)
            docs.extend([row] * len(counts))
            tfs.extend(counts.values())
        self._rows += count
        self._total_length += int(self._lengths[base : base + count].sum())
        term_array = np.array(terms, dtype=np.int32)
        self._count_terms(term_array)
        self._segments.append(
            _make_segment(
                base, count, term_array, np.array(docs, dtype=np.int32), np.array(tfs, dtype=np.int32), self._lengths
            )
        )
        while len(self._segments) > 1:
            last, before = self._segments[-1], self._segments[-2]
            if before.rows > 2 * last.rows or before.rows + last.rows > MAX_SEGMENT:
                break
            self._segments[-2:] = [self._merged(before, last)]

    def _count_terms(self, terms: np.ndarray) -> None:
        if len(self._vocabulary) > len(self._frequency):
            bigger = np.zeros(max(len(self._vocabulary), 2 * len(self._frequency)), dtype=np.int64)
            bigger[: len(self._frequency)] = self._frequency
            self._frequency = bigger
        if len(terms):
            found, times = np.unique(terms, return_counts=True)
            self._frequency[found] += times

    def _merged(self, a: _Segment, b: _Segment) -> _Segment:
        parts = [(s, np.repeat(s.terms, np.diff(s.offsets)), s.docs + (s.base - a.base)) for s in (a, b)]
        return _make_segment(
            a.base,
            a.rows + b.rows,
            np.concatenate([terms for _, terms, _ in parts]),
            np.concatenate([docs for _, _, docs in parts]).astype(np.int32),
            np.concatenate([s.tfs for s, _, _ in parts]),
            self._lengths,
        )

    def keeping(self, rows: np.ndarray) -> LexicalIndex:
        """An index of these rows only, numbered again in the same order."""
        new = LexicalIndex()
        new._vocabulary = dict(self._vocabulary)
        renumbered = np.full(self._rows, -1, dtype=np.int64)
        renumbered[rows] = np.arange(len(rows))
        new._lengths = np.r_[self._lengths[rows], np.zeros(1024, dtype=np.int32)]
        new._rows = len(rows)
        new._total_length = int(self._lengths[rows].sum())
        pending: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        for segment in self._segments:
            terms = np.repeat(segment.terms, np.diff(segment.offsets))
            docs = renumbered[segment.base + segment.docs]
            keep = docs >= 0
            pending.append((terms[keep], docs[keep], segment.tfs[keep]))
        if pending and len(rows):
            terms, docs, tfs = (np.concatenate([p[i] for p in pending]) for i in range(3))
            order = np.argsort(docs, kind="stable")
            terms, docs, tfs = terms[order], docs[order], tfs[order]
            new._count_terms(terms)
            for base in range(0, len(rows), MAX_SEGMENT):
                low, high = np.searchsorted(docs, [base, base + MAX_SEGMENT])
                new._segments.append(
                    _make_segment(
                        base,
                        min(MAX_SEGMENT, len(rows) - base),
                        terms[low:high],
                        (docs[low:high] - base).astype(np.int32),
                        tfs[low:high],
                        new._lengths,
                    )
                )
        return new

    # --- search ---

    def _terms(self, query: str) -> tuple[list[int], bool]:
        """Identifiers of the distinct terms of the query, in a fixed order, and
        whether all of them exist."""
        words = sorted(set(analyze(query)))
        known = [self._vocabulary[w] for w in words if w in self._vocabulary]
        known = [t for t in known if t < len(self._frequency) and self._frequency[t] > 0]
        return known, bool(words) and len(known) == len(words)

    def _idf(self, term: int) -> float:
        frequency = int(self._frequency[term])
        return math.log(1 + (self._rows - frequency + 0.5) / (frequency + 0.5))

    def postings(self, query: str) -> int:
        return int(sum(self._frequency[t] for t in self._terms(query)[0]))

    def search(
        self, query: str, k: int, *, allowed: np.ndarray | None = None, require_all: bool = False
    ) -> tuple[np.ndarray, np.ndarray]:
        """The best `k` rows by BM25, best first and then by row, and their
        scores. With `require_all`, only rows with every word of the query."""
        self.last_scored = 0
        terms, complete = self._terms(query)
        if not terms or k <= 0 or (require_all and not complete):
            return _NOTHING
        from src.engine import lexical_kernels as kernels

        k = min(k, self._rows)
        heap_scores, heap_rows, size = np.empty(k), np.empty(k, dtype=np.int64), 0
        average = self._total_length / self._rows
        min_match = len(terms) if require_all else 1
        no_filter = np.empty(0, dtype=np.uint8)
        for segment in self._segments:
            at = [(t, i) for t in terms if (i := self._place(segment, t)) >= 0]
            if len(at) < min_match:
                continue
            places = np.array([i for _, i in at])
            idf = np.array([self._idf(t) for t, _ in at])
            tf, length = segment.term_tf[places].astype(float), segment.term_len[places].astype(float)
            bound = idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / average))
            size, scored = kernels.top_k(
                segment.docs, segment.tfs, segment.offsets[places], segment.offsets[places + 1],
                segment.block_offsets[places], segment.block_offsets[places + 1], segment.block_last, segment.block_tf,
                segment.block_len, idf, bound, self._lengths, K1, B, average,
                no_filter if allowed is None else allowed, allowed is not None, segment.base, k, min_match, heap_scores,
                heap_rows, size,
            )  # fmt: skip
            self.last_scored += scored
        order = np.lexsort((heap_rows[:size], -heap_scores[:size]))
        return heap_rows[order], heap_scores[order]

    @staticmethod
    def _place(segment: _Segment, term: int) -> int:
        at = int(np.searchsorted(segment.terms, term))
        return at if at < len(segment.terms) and segment.terms[at] == term else -1

    def search_exhaustive(
        self, query: str, k: int, *, allowed: np.ndarray | None = None, require_all: bool = False
    ) -> tuple[np.ndarray, np.ndarray]:
        """The reference: scores every posting."""
        terms, complete = self._terms(query)
        if not terms or (require_all and not complete):
            return _NOTHING
        average = self._total_length / self._rows
        scores, matched = np.zeros(self._rows), np.zeros(self._rows, dtype=np.int32)
        for term in terms:
            idf = self._idf(term)
            for segment in self._segments:
                at = self._place(segment, term)
                if at < 0:
                    continue
                where = slice(segment.offsets[at], segment.offsets[at + 1])
                rows = segment.base + segment.docs[where].astype(np.int64)
                tf, length = segment.tfs[where].astype(float), self._lengths[rows].astype(float)
                scores[rows] += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / average))
                matched[rows] += 1
        found = matched >= (len(terms) if require_all else 1)
        if allowed is not None:
            found &= allowed[: self._rows] != 0
        rows = np.flatnonzero(found)
        order = np.lexsort((rows, -scores[rows]))[:k]
        return rows[order], scores[rows[order]]
