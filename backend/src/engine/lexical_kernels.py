"""Compiled inner loop of the lexical search. See `lexical.py`."""
from __future__ import annotations

import numpy as np
from numba import njit

_OPTIONS = {"nogil": True, "cache": True, "boundscheck": False}
BLOCK = 128
NO_DOC = np.int32(2**31 - 1)
# Upper bounds are sums in another order than the scores: this covers the rounding.
SLACK = 1e-9


@njit(**_OPTIONS)
def term_score(idf, tf, length, k1, b, average):
    return idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / average))


@njit(**_OPTIONS)
def _worse(score_a, row_a, score_b, row_b):
    return score_a < score_b or (score_a == score_b and row_a > row_b)


@njit(**_OPTIONS)
def _replace_worst(scores, rows, size, score, row):
    at = 0
    while True:
        child = 2 * at + 1
        if child >= size:
            break
        if child + 1 < size and _worse(scores[child + 1], rows[child + 1], scores[child], rows[child]):
            child += 1
        if not _worse(scores[child], rows[child], score, row):
            break
        scores[at], rows[at] = scores[child], rows[child]
        at = child
    scores[at], rows[at] = score, row


@njit(**_OPTIONS)
def _insert(scores, rows, size, score, row):
    at = size
    while at > 0:
        parent = (at - 1) >> 1
        if not _worse(score, row, scores[parent], rows[parent]):
            break
        scores[at], rows[at] = scores[parent], rows[parent]
        at = parent
    scores[at], rows[at] = score, row


@njit(**_OPTIONS)
def _first_block(block_last, block, block_end, target):
    """The first block whose last document is not before the target."""
    step = 1
    low = block
    while block < block_end and block_last[block] < target:
        low = block + 1
        block += step
        step *= 2
    high = min(block, block_end)
    while low < high:
        middle = (low + high) >> 1
        if block_last[middle] < target:
            low = middle + 1
        else:
            high = middle
    return low


@njit(**_OPTIONS)
def top_k(
    docs, tfs, starts, ends, block_starts, block_ends, block_last, block_tf, block_len, idf, bound, lengths, k1, b,
    average, allowed, use_allowed, base, k, min_match, heap_scores, heap_rows, heap_size,
):  # fmt: skip
    """Block-max WAND over one segment: the best `k` documents by BM25, of those
    that contain at least `min_match` of the terms.

    Posting lists are walked together in document order. A document is scored
    only if the best its terms could give, first over their whole lists and then
    over the blocks around it, beats the worst of the results so far. A later
    document with the same score is not better, so "not more" is enough to skip.

    The heap goes on from one segment to the next. Returns its size and how many
    documents were scored."""
    terms = starts.shape[0]
    position = starts.copy()
    block = block_starts.copy()  # of the current document
    shallow = block_starts.copy()  # may be ahead: only to look at bounds
    current = np.empty(terms, dtype=np.int32)
    order = np.empty(terms, dtype=np.int64)
    for t in range(terms):
        current[t] = docs[position[t]] if position[t] < ends[t] else NO_DOC
        order[t] = t
    scored = 0

    while True:
        for i in range(1, terms):
            t = order[i]
            j = i - 1
            while j >= 0 and current[order[j]] > current[t]:
                order[j + 1] = order[j]
                j -= 1
            order[j + 1] = t
        worst = heap_scores[0] if heap_size == k else -np.inf

        pivot_at = -1
        total = 0.0
        for i in range(terms):
            t = order[i]
            if current[t] == NO_DOC:
                break
            total += bound[t]
            if i + 1 >= min_match and total * (1 + SLACK) > worst:
                pivot_at = i
                break
        if pivot_at < 0:
            break
        pivot = current[order[pivot_at]]
        while pivot_at + 1 < terms and current[order[pivot_at + 1]] == pivot:
            pivot_at += 1

        # What the blocks that could hold the pivot may give at most, and how far that holds.
        target = current[order[pivot_at + 1]] if pivot_at + 1 < terms else NO_DOC
        total = 0.0
        for i in range(pivot_at + 1):
            t = order[i]
            shallow[t] = _first_block(block_last, max(shallow[t], block[t]), block_ends[t], pivot)
            if shallow[t] < block_ends[t]:
                at = shallow[t]
                total += term_score(idf[t], float(block_tf[at]), float(block_len[at]), k1, b, average)
                if block_last[at] + 1 < target:
                    target = block_last[at] + 1
        if total * (1 + SLACK) > worst:
            if current[order[0]] == pivot:
                if not use_allowed or allowed[base + pivot]:
                    score = 0.0
                    for t in range(terms):  # always in this order, so that the sum is always the same
                        if current[t] == pivot:
                            score += term_score(
                                idf[t], float(tfs[position[t]]), float(lengths[base + pivot]), k1, b, average
                            )
                    scored += 1
                    if heap_size < k:
                        _insert(heap_scores, heap_rows, heap_size, score, base + pivot)
                        heap_size += 1
                    elif score > worst:
                        _replace_worst(heap_scores, heap_rows, heap_size, score, base + pivot)
                target = pivot + 1
            else:
                target = pivot  # bring the ones that are behind up to it

        for i in range(pivot_at + 1):
            t = order[i]
            if current[t] >= target:
                continue
            block[t] = _first_block(block_last, block[t], block_ends[t], target)
            if block[t] >= block_ends[t]:
                position[t] = ends[t]
                current[t] = NO_DOC
                continue
            low = max(position[t], starts[t] + (block[t] - block_starts[t]) * BLOCK)
            high = min(ends[t], starts[t] + (block[t] - block_starts[t] + 1) * BLOCK)
            while low < high:
                middle = (low + high) >> 1
                if docs[middle] < target:
                    low = middle + 1
                else:
                    high = middle
            position[t] = low
            current[t] = docs[low]
    return heap_size, scored
