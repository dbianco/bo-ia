# 4. Hybrid ranking engine - DONE

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

## Status

Implemented, and closed with one exception: the quality criterion is not met at full scale (see Quality). Verified on 2026-11-26 on an Apple M4 Pro (14 cores, 24 GB, macOS 27.2, PostgreSQL 16 with pgvector in Docker): `ruff check src tests ../web` clean; 1,427 tests of the fast suite pass; the real model test and both search implementations of the `slow` suite pass; `pytest -m docker` passes with the real model, in a separate compose project. By hand: 48 queries, with and without filters, gave the same response format on both implementations, and 44 the same results; the other 4 are one query in `hybrid` and `all` modes, where each implementation ranks text in its own way. `scale-search` with seed 42 and 1,000,380 fragments reproduced the quality figures, including the unmet one (0.484 against 0.515); no difference in 400 lexical searches; recall@10 at width 128 of 0.973 without filters and 1.000 keeping 1%; hybrid p95 4.4 ms without reading the rows.

**Closed with an exception:** on 2026-11-26 the owner confirmed that the plan is done although hybrid nDCG@10 on paraphrases at 868,000 documents is 0.484 against 0.515. The criterion stays as written and counts as not met. The PostgreSQL run at this size was not repeated in that verification, because building its index needed more shared memory than the container had: the latency comparison with PostgreSQL rests on the earlier measurement under Numbers, made on another machine and before the analyzer fix.

| Criterion | Result | Test |
|---|---|---|
| Pruned top 10 equals the exhaustive one | Met: 0 differences in 400 searches (200 queries, any word and every word), scoring 0.4% of the postings | `tests/engine/test_lexical.py::test_the_pruned_top_equals_the_exhaustive_one`, `tests/benchmark/test_scale_search.py::test_pruned_lexical_results_equal_the_exhaustive_ones` |
| Recall@10 of at least 0.95, also under filters that keep 1% | Met with the default width of 128: 0.973 without filters, 0.976 keeping 30%, 0.991 keeping 10%, 1.000 keeping 1% (scanned) | `tests/vector/test_hnsw.py::test_recall_under_filters`, `tests/benchmark/test_scale_search.py::test_recall_with_and_without_filters` |
| Hybrid p95 below PostgreSQL, proposed under 50 ms | Met: 26.5 ms in the engine. With reading the 10 rows of the result (15.7 ms) some 42 ms, against 102 ms for PostgreSQL | `python -m src.benchmark scale-search`, with and without `--database-url` |
| Hybrid nDCG@10 not below the better of its parts on paraphrases | Met at 1,200 and 20,000 documents (equal to semantic). **Not met** at 868,000: 0.484 against 0.515, accepted by the owner | `tests/engine/test_engine.py::test_hybrid_is_not_worse_than_its_parts_on_paraphrases` |
| Curve of recall and latency for three widths or more | Below | `tests/benchmark/test_scale_search.py` |

### Numbers

Measured before a fix of the analyzer for short plurals such as "obras" (plan 10).

Gazette profile, seed 42, 868,000 documents, 1,000,380 fragments, 200 queries. Hashed provider, dimension 1024, synonym coverage 0.8, threshold 0.45. Four virtual CPUs, Intel Xeon (Ice Lake) at 2.60 GHz, 15 GB. Building everything, with the embedding, takes 25 minutes.

Recall@10 against an exact scan, and p95:

| Width | No filter | Keeps 30% | Keeps 10% | Keeps 1% |
|---|---|---|---|---|
| 32 | 0.928, 1.3 ms | 0.968, 1.9 ms | 0.982, 3.2 ms | 1.000, 13 ms |
| 64 | 0.957, 1.4 ms | 0.973, 2.4 ms | 0.987, 5.5 ms | 1.000, 13 ms |
| **128** | **0.973, 2.0 ms** | **0.976, 4.3 ms** | **0.991, 9.3 ms** | **1.000, 14 ms** |
| 256 | 0.977, 3.3 ms | 0.981, 7.1 ms | 0.997, 17 ms | 1.000, 14 ms |
| 512 | 0.980, 5.6 ms | 0.986, 13 ms | 0.998, 30 ms | 1.000, 14 ms |
| exact scan | 288 ms | 72 ms | 33 ms | 13 ms |

| Mode, limit 10 | p95 in the engine | nDCG@10, paraphrase | nDCG@10, same vocabulary |
|---|---|---|---|
| lexical (any word) | 22 ms | 0.000 | 0.964 |
| semantic | 9 ms | 0.515 | 0.913 |
| hybrid | 27 ms | 0.484 | 0.979 |
| all | 27 ms | 0.485 | 0.979 |

The same queries on PostgreSQL with its caches warm (`shared_buffers` of 2 GB; pgvector with its default width of 40), including the embedding of the query and reading the rows. Loading took 29 minutes. Reading the 10 rows of a result, which the engine's figures above do not include, has a p95 of 15.7 ms.

| Mode, limit 10 | p95 | nDCG@10, paraphrase | nDCG@10, same vocabulary |
|---|---|---|---|
| semantic | 54 ms | 0.476 | 0.882 |
| hybrid | 102 ms | 0.455 | 0.971 |
| all | 84 ms | 0.455 | 0.960 |

### Quality

With 868,000 documents, 31 of the 100 paraphrase queries have text matches: 50 documents that contain every word of the query, none of them relevant, because the words are in planted distractors (an address, a company name). The fusion raises them, and the paraphrase queries lose 0.031. The queries that share vocabulary gain 0.066, and all together improve from 0.714 to 0.732. PostgreSQL loses in the same way (0.476 to 0.455). At 60,000 documents, where 2 queries have such matches, the loss is 0.001 or none, the same with text weights from 1 down to 0.1: a document in both rankings is raised whatever the weight, and a smaller one gives up part of the gain. The target is not changed. It is a limit of fusing by rank. The owner accepted this result: the hybrid mode improves all queries together.

## Decisions

- **Language.** Python, with the inner loops compiled by Numba: a dependency that installs with pip, no second toolchain. The latency target is met. Numba only loads with the engine or with 20,000 subscriptions or more; compiling takes some seconds the first time, and is cached.
- **Memory.** Vectors in memory: about 4 GB per million fragments, 1 GB of 8-bit codes for the traversal, and 0.5 GB for the rest. Mapping them from disk goes with the persistence of plan 5.
- **Scores shown** are still cosine similarities, computed exactly. A text match outside the vector candidates now shows its similarity, and not 0.
- **Text matches** still need every word of the query, as now: the results that skip the threshold do not change. BM25 with any word is there for comparison (`engine-lexical`): on paraphrases it would only add noise.
- **Threshold.** Applied in the vector search. In hybrid mode with text matches it applies after the fusion, because the place of a text match in the vector ranking counts, as now.
- **Fusion weights.** `RRF_WEIGHTS` (vector, text), equal by default as now.
- **Filters during the traversal.** A row that is not allowed leads to others and is not a result. When that would cost more than scanning the rows that are, they are scanned: the limit grows with the square root of the size and the width.
- **Filter values** are sorted lists that become bitmaps when used (the last 32 are kept), instead of one bitmap always: an installation has many values with few rows.
- **Vectors of 8 bits in the graph.** In a large index the time goes in waiting for memory. Results are scored again with the full vectors.
- **Setting.** `SEARCH_ENGINE`: `postgres` by default. With `engine`, PostgreSQL answers until it has loaded. It becomes the default when plan 5 makes starts fast.
- **Keeping it current.** As in plan 3: triggers record the transaction of each change to a document or its fragments, and a search reads first what changed.
