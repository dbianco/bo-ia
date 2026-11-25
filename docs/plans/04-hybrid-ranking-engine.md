# 4. Hybrid ranking engine

## Goal

An in-process search engine built here: an inverted index with BM25, a vector index, metadata filters applied during the search, and rank fusion. It replaces PostgreSQL full-text search and pgvector for queries, and is measured against them.

## Why

Search is currently a thin layer over two PostgreSQL features. The interesting behaviour, how filters interact with approximate vector search and how the two rankings are combined, is outside the project's control and cannot be tuned or measured in detail.

## Current state

- `backend/src/api/search.py` runs the queries. Vector search uses the pgvector HNSW index `ix_fragmentos_embedding_hnsw` (cosine); text search uses a `tsvector` column with `ts_rank`.
- It fetches more candidates than requested, filters by the similarity threshold in Python (`backend/src/processor/threshold.py`), then cuts to the limit.
- `backend/src/processor/hybrid.py` fuses the two rankings with Reciprocal Rank Fusion, constant 60.
- Filters declared in `installation.yaml` are applied in SQL.

## Design

**Lexical index**

- A Spanish analyzer: lowercasing, accent folding, stopwords, light stemming.
- An inverted index with postings and term frequencies, scored with BM25.
- Top-k retrieval that skips documents that cannot enter the result (for example block-max WAND), since scoring every posting does not hold at scale.

**Vector index**

- HNSW with cosine similarity, written here: layered graph, neighbour selection heuristic, configurable construction and search widths.
- Filters applied during traversal, so a filter narrows the candidates instead of discarding results afterwards.
- An exact scan when the filter leaves few candidates.

**Metadata filters**

- One bitmap per filter value, sorted arrays for ranges, combined with AND across keys and OR within a key, as the API already defines.

**Fusion**

- Reciprocal Rank Fusion with configurable weights, kept compatible with the current behaviour.
- The similarity threshold is applied inside the vector search, not after it.

**Integration**

- A search interface with two implementations: PostgreSQL (the reference) and the new engine. The API and its response format do not change.
- PostgreSQL stays the system of record; the engine is built from it and kept current as documents are ingested.

## The hard parts

- **Filtered approximate search.** Recall collapses when a filter is selective unless the traversal is designed for it.
- **Recall versus latency.** The search width trades one for the other; the benchmark has to show the curve, not a single point.
- **Dynamic pruning.** Skipping postings without changing the top-k result is easy to get subtly wrong.
- **Agreement with the reference.** Scores differ from PostgreSQL's, so correctness is defined on rankings against exact computation, not on equal numbers.

## Milestones

1. Search interface and the PostgreSQL adapter in the benchmark harness.
2. Analyzer and inverted index with exhaustive BM25, checked against hand-computed scores.
3. Dynamic pruning, with tests that the top-k equals the exhaustive result.
4. HNSW without filters; recall against an exact scan.
5. Filter bitmaps, filtered traversal and the exact-scan fallback.
6. Fusion, threshold, and the API switched over behind a setting.

## Success criteria

Measured on the synthetic corpus from plan 1 at a proposed scale of 1,000,000 fragments:

- Lexical: the pruned top-10 equals the exhaustive top-10 on every benchmark query.
- Vector: recall@10 of at least 0.95 against an exact scan, including under filters that keep 1% of the corpus.
- Latency: p95 for a hybrid query below the PostgreSQL reference on the same machine; proposed absolute target under 50 ms.
- Quality: hybrid nDCG@10 not below the better of lexical and semantic on the paraphrase queries.
- A published recall and latency curve for at least three search widths.

## Open decisions

- Language. Python keeps one codebase but makes the latency target hard; a compiled core (Rust or C) behind a Python binding makes it reachable at the cost of a second toolchain.
- Whether the engine holds vectors in memory or memory-maps them from disk.
- Whether result scores shown to users remain cosine similarities, since the threshold is defined on them.
- Persistence, updates and deletes: see plan 5.
