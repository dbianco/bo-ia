"""Compiled inner loops of the vector index.

Plain Python that Numba compiles the first time it runs (a few seconds, then
cached on disk). Every function releases the GIL and none starts threads: the
callers run them from a thread pool, which is safe to use from several API
threads at once.

Vectors are unit length, so the inner product is the cosine similarity. The graph
works on codes of 8 bits per coordinate, a quarter of the memory: in a large
index the time goes in waiting for memory, not in multiplying. A code is wrong
by some thousandths; whoever needs the exact similarity computes it afterwards,
for the few rows that matter.

Order is always (similarity, then lower row), so that results do not depend on
timing."""
from __future__ import annotations

import numpy as np
from llvmlite import ir
from numba import njit, types
from numba.core import cgutils
from numba.extending import intrinsic

_OPTIONS = {"nogil": True, "cache": True, "boundscheck": False}
CACHE_LINE = 64
GROUP = 8  # candidates that are expanded together
QUERY_LEVELS = 2047  # a query has 12 bits per coordinate, so that a sum fits in 32


@intrinsic
def _prefetch(typingctx, array, row, column):
    """Asks for a piece of a row that will be read soon, without waiting for it."""

    def generate(context, builder, signature, arguments):
        array_type = signature.args[0]
        value = context.make_array(array_type)(context, builder, arguments[0])
        pointer = cgutils.get_item_pointer(
            context, builder, array_type, value, [arguments[1], arguments[2]], wraparound=False
        )
        byte, integer = ir.IntType(8).as_pointer(), ir.IntType(32)
        function = cgutils.get_or_insert_function(
            builder.module, ir.FunctionType(ir.VoidType(), [byte, integer, integer, integer]), "llvm.prefetch.p0i8"
        )
        builder.call(function, [builder.bitcast(pointer, byte), integer(0), integer(2), integer(1)])
        return context.get_dummy_value()

    return types.void(array, types.int64, types.int64), generate


@njit(**_OPTIONS)
def encode(vectors, codes, scales, lo, hi):
    """8-bit codes of the rows `lo` to `hi - 1`. A row is its code times its scale."""
    dim = vectors.shape[1]
    for row in range(lo, hi):
        largest = np.float32(0.0)
        for i in range(dim):
            largest = max(largest, abs(vectors[row, i]))
        scale = largest / np.float32(127.0)
        scales[row] = scale
        for i in range(dim):
            codes[row, i] = np.int8(round(vectors[row, i] / scale)) if scale > 0 else np.int8(0)


@njit(**_OPTIONS)
def _code_similarity(codes, scales, row, query):
    total = np.int32(0)
    code = codes[row]
    for i in range(code.shape[0]):
        total = np.int32(total + np.int32(np.int32(code[i]) * np.int32(query[i])))
    return np.float32(total) * scales[row]


@njit(**_OPTIONS)
def _rows_similarity(codes, scales, a, b):
    total = np.int32(0)
    code_a, code_b = codes[a], codes[b]
    for i in range(code_a.shape[0]):
        total = np.int32(total + np.int32(np.int16(code_a[i] * code_b[i])))
    return np.float32(total) * scales[a] * scales[b]


@njit(fastmath=True, inline="never", **_OPTIONS)
def dot(a, b):
    total = np.float32(0.0)
    for i in range(a.shape[0]):
        total += a[i] * b[i]
    return total


# --- binary heaps over parallel arrays --------------------------------------
# `sign` is 1 for a heap whose root is the best entry, -1 for the worst.


@njit(**_OPTIONS)
def _before(sim_a, row_a, sim_b, row_b, sign):
    if sim_a != sim_b:
        return (sim_a > sim_b) == (sign == 1)
    return (row_a < row_b) == (sign == 1)


@njit(**_OPTIONS)
def _push(sims, rows, size, sim, row, sign):
    at = size
    while at > 0:
        parent = (at - 1) >> 1
        if not _before(sim, row, sims[parent], rows[parent], sign):
            break
        sims[at], rows[at] = sims[parent], rows[parent]
        at = parent
    sims[at], rows[at] = sim, row


@njit(**_OPTIONS)
def _sift_root(sims, rows, size, sim, row, sign):
    """Puts an entry in the place of the root of a heap of `size` entries."""
    at = 0
    while True:
        child = 2 * at + 1
        if child >= size:
            break
        if child + 1 < size and _before(sims[child + 1], rows[child + 1], sims[child], rows[child], sign):
            child += 1
        if not _before(sims[child], rows[child], sim, row, sign):
            break
        sims[at], rows[at] = sims[child], rows[child]
        at = child
    sims[at], rows[at] = sim, row


@njit(**_OPTIONS)
def _grown(values):
    bigger = np.empty(values.shape[0] * 2, dtype=values.dtype)
    bigger[: values.shape[0]] = values
    return bigger


# --- graph search ------------------------------------------------------------


@njit(**_OPTIONS)
def descend(codes, scales, upper_start, upper_links, width, query, entry, entry_level, stop_level):
    """Greedy walk through the upper layers, down to `stop_level` (excluded).
    `query` is in code units, and so are the similarities compared here."""
    best, best_sim = entry, _code_similarity(codes, scales, entry, query)
    for level in range(entry_level, stop_level, -1):
        moved = True
        while moved:
            moved = False
            base = upper_start[best] + (level - 1) * width
            for i in range(width):
                row = upper_links[base + i]
                if row < 0:
                    break
                sim = _code_similarity(codes, scales, row, query)
                if sim > best_sim:
                    best, best_sim, moved = row, sim, True
    return best


@njit(**_OPTIONS)
def search_layer(
    codes, scales, links, starts, level, width, query, query_scale, entries, ef, visited, tag, allowed, use_allowed,
    threshold, slack,
):  # fmt: skip
    """Best-first search of one layer, from the rows in `entries`.

    Keeps the best `ef` rows seen that are allowed, and also, when `threshold`
    is finite, every allowed row at or above it, however many there are. It goes
    on while the next candidate may still matter: it is among the best `ef`
    seen, or within `slack` of the threshold.

    Level 0 is a dense array of links; the upper layers are addressed by `starts`.
    Returns (rows, similarities) unordered, and how many similarities it computed."""
    cand_sims = np.empty(256, dtype=np.float32)
    cand_rows = np.empty(256, dtype=np.int32)
    best_sims = np.empty(ef, dtype=np.float32)
    best_rows = np.empty(ef, dtype=np.int32)
    over_sims = np.empty(64, dtype=np.float32)
    over_rows = np.empty(64, dtype=np.int32)
    fresh = np.empty(width * GROUP, dtype=np.int32)
    cands = best = over = 0
    explore_from = threshold - slack
    dim = codes.shape[1]
    computed = 0
    at_entry = 0

    while True:
        # The rows to look at: first the entries, then the neighbours of the best candidate.
        count = 0
        if at_entry < entries.shape[0]:
            while at_entry < entries.shape[0] and count < fresh.shape[0]:
                row = entries[at_entry]
                at_entry += 1
                if visited[row] != tag:
                    visited[row] = tag
                    fresh[count] = row
                    count += 1
        else:
            if cands == 0:
                break
            sim = cand_sims[0]
            if best == ef and sim < best_sims[0] and sim < explore_from:
                break
            # Several at a time, if they will be expanded anyway: the rows they
            # lead to are then fetched from memory together.
            expanded = 0
            while expanded < GROUP and cands > 0:
                sim, row = cand_sims[0], cand_rows[0]
                if expanded > 0 and sim < explore_from and not (expanded < 2 and (best < ef or sim > best_sims[0])):
                    break
                expanded += 1
                cands -= 1
                if cands > 0:
                    _sift_root(cand_sims, cand_rows, cands, cand_sims[cands], cand_rows[cands], 1)
                base = row * width if level == 0 else starts[row] + (level - 1) * width
                for i in range(width):
                    other = links[base + i]
                    if other < 0:
                        break
                    if visited[other] != tag:
                        visited[other] = tag
                        fresh[count] = other
                        count += 1

        for i in range(count):
            for column in range(0, dim, CACHE_LINE):
                _prefetch(codes, np.int64(fresh[i]), np.int64(column))
        for i in range(count):
            other = fresh[i]
            sim = _code_similarity(codes, scales, other, query) * query_scale
            computed += 1
            if not (best < ef or sim > best_sims[0] or sim >= explore_from):
                continue
            if cands == cand_sims.shape[0]:
                cand_sims, cand_rows = _grown(cand_sims), _grown(cand_rows)
            _push(cand_sims, cand_rows, cands, sim, other, 1)
            cands += 1
            if use_allowed and not allowed[other]:
                continue
            if sim >= threshold:
                if over == over_sims.shape[0]:
                    over_sims, over_rows = _grown(over_sims), _grown(over_rows)
                over_sims[over], over_rows[over] = sim, other
                over += 1
            if best < ef:
                _push(best_sims, best_rows, best, sim, other, -1)
                best += 1
            elif sim > best_sims[0]:
                _sift_root(best_sims, best_rows, ef, sim, other, -1)
    return best_rows[:best], best_sims[:best], over_rows[:over], over_sims[:over], computed


# --- construction ------------------------------------------------------------


@njit(**_OPTIONS)
def select_neighbours(codes, scales, cand_rows, cand_sims, count, out):
    """The diversity heuristic of HNSW: a candidate is kept if it is closer to
    the new row than to any neighbour already kept, so that links point in
    different directions. Candidates come best first. If there is room left it
    is filled with the best of the rest: sparse regions stay connected."""
    limit = out.shape[0]
    kept = 0
    skipped = np.empty(count, dtype=np.int32)
    skips = 0
    for i in range(count):
        if kept == limit:
            break
        row = cand_rows[i]
        good = True
        for j in range(kept):
            # "or equal": copies of one vector must not take all the links.
            if _rows_similarity(codes, scales, row, out[j]) >= cand_sims[i]:
                good = False
                break
        if good:
            out[kept] = row
            kept += 1
        else:
            skipped[skips] = row
            skips += 1
    for i in range(skips):
        if kept == limit:
            break
        out[kept] = skipped[i]
        kept += 1
    for i in range(kept, limit):
        out[i] = -1
    return kept


@njit(**_OPTIONS)
def _sorted_best_first(rows, sims):
    """By similarity, and by row among equals (rows arrive in any order)."""
    by_row = np.argsort(rows)
    order = by_row[np.argsort(-sims[by_row], kind="mergesort")]
    return rows[order], sims[order]


@njit(**_OPTIONS)
def choose_links(
    codes, scales, queries, query_scales, links0, upper_start, upper_links, width, first, lo, hi, levels, entry,
    entry_level, ef, visited, tag, out0, out_upper,
):  # fmt: skip
    """The neighbours of the rows `first + lo` to `first + hi - 1`, from the graph
    and from the earlier rows of the same batch, which are not in the graph yet.
    `queries` are the rows of the batch as queries. Reads the graph only, so that
    several threads may run it. Returns the last tag used in `visited`."""
    no_filter = np.empty(0, dtype=np.uint8)
    never = np.float32(np.inf)
    for position in range(lo, hi):
        query, query_scale = queries[position], query_scales[position]
        top = levels[first + position]
        mate_sims = np.empty(position, dtype=np.float32)
        for other in range(position):
            mate_sims[other] = _rows_similarity(codes, scales, first + position, first + other)
        at = entry
        if entry >= 0 and entry_level > top:
            at = descend(codes, scales, upper_start, upper_links, width, query, entry, entry_level, top)
        for level in range(top, -1, -1):
            room = 2 * width if level == 0 else width
            rows = np.empty(0, dtype=np.int32)
            sims = np.empty(0, dtype=np.float32)
            if entry >= 0 and level <= entry_level:
                tag += 1
                source = links0 if level == 0 else upper_links
                rows, sims, _, _, _ = search_layer(
                    codes, scales, source, upper_start, level, room, query, query_scale,
                    np.array([at], dtype=np.int32), ef, visited, tag, no_filter, False, never, np.float32(0.0),
                )  # fmt: skip
            found = rows.shape[0]
            mates = 0
            for other in range(position):
                if levels[first + other] >= level:
                    mates += 1
            all_rows = np.empty(found + mates, dtype=np.int32)
            all_sims = np.empty(found + mates, dtype=np.float32)
            all_rows[:found], all_sims[:found] = rows, sims
            for other in range(position):
                if levels[first + other] >= level:
                    all_rows[found], all_sims[found] = first + other, mate_sims[other]
                    found += 1
            all_rows, all_sims = _sorted_best_first(all_rows, all_sims)
            if rows.shape[0] > 0:
                for i in range(all_rows.shape[0]):
                    if all_rows[i] < first:  # the next layer starts from a row of the graph
                        at = all_rows[i]
                        break
            out = out0[position] if level == 0 else out_upper[position, level - 1]
            select_neighbours(codes, scales, all_rows, all_sims, min(all_rows.shape[0], ef), out)
    return tag


@njit(**_OPTIONS)
def add_back_links(codes, scales, links, bases, targets, sources, room, lo, hi):
    """Adds `sources[i]` to the links of `targets[i]`, whose list is at `bases[i]`.
    Pairs come grouped by target, and each target is in one thread only. A list
    that does not have room keeps the best by the same heuristic."""
    i = lo
    while i < hi:
        target, base = targets[i], bases[i]
        end = i
        while end < hi and targets[end] == target:
            end += 1
        have = 0
        while have < room and links[base + have] >= 0:
            have += 1
        if have + (end - i) <= room:
            for j in range(i, end):
                links[base + have] = sources[j]
                have += 1
        else:
            rows = np.empty(have + end - i, dtype=np.int32)
            sims = np.empty(have + end - i, dtype=np.float32)
            for j in range(have):
                rows[j] = links[base + j]
            for j in range(i, end):
                rows[have + j - i] = sources[j]
            for j in range(rows.shape[0]):
                for column in range(0, codes.shape[1], CACHE_LINE):
                    _prefetch(codes, np.int64(rows[j]), np.int64(column))
            for j in range(rows.shape[0]):
                sims[j] = _rows_similarity(codes, scales, rows[j], target)
            rows, sims = _sorted_best_first(rows, sims)
            out = np.empty(room, dtype=np.int32)
            select_neighbours(codes, scales, rows, sims, rows.shape[0], out)
            for j in range(room):
                links[base + j] = out[j]
        i = end


@njit(fastmath=True, **_OPTIONS)
def scan_best(vectors, rows, queries, out):
    """Exact similarity of the best of the queries to each of the rows."""
    ahead = 8
    for i in range(rows.shape[0]):
        if i + ahead < rows.shape[0]:
            for column in range(0, vectors.shape[1], CACHE_LINE // 4):
                _prefetch(vectors, np.int64(rows[i + ahead]), np.int64(column))
        best = np.float32(-np.inf)
        for j in range(queries.shape[0]):
            best = max(best, dot(vectors[rows[i]], queries[j]))
        out[i] = best
