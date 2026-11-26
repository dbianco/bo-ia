# 1. Synthetic corpus and benchmark harness

## Goal

A deterministic generator of gazette and tender documents with planted relevance, and a harness that runs any search or matching implementation against it and reports recall and latency. The right answers are known by construction, so no human or model judgments are needed.

## Why

- Today quality is checked with a few seeded sample documents and tests that use fake embeddings. Nothing measures recall.
- The companion project measured retrieval with 60 queries judged by language models. Those judgments cap recall@10 at 0.51 and favour the modes that built the pool. Planted relevance removes both problems.
- Live sources cannot be used in a repeatable benchmark: they change, block automated clients, and need a network.

## Current state

- `backend/src/seed/` loads a handful of sample gazette documents.
- Connector tests run against local fixtures; nothing generates documents at scale.
- There is no benchmark command and no recall metric in this repository.

## Design

**Generator**

- Input: a seed, a corpus size, and a profile (gazette or tenders).
- A document is built from a *topic* (for example a road works tender, a company incorporation, a judicial notice), a template with slots, and metadata drawn from the installation's declared filters (province, municipality, contracting body, amount).
- Each topic has several vocabularies that say the same thing in different words. A query uses one vocabulary and its relevant documents use another, so lexical search alone cannot find them all.
- Republication: a share of notices is repeated on following days with only the date and notice number changed, as the real gazette does.
- Distractors: documents that share words with a query but belong to another topic.
- Output: documents in the ingestion contract (`backend/src/ingestor/contract.py`), plus a truth file.

**Truth file**

- For each query: the ids of relevant documents with a grade (exact topic, related topic).
- For each subscription: the ids of documents that must match, given its text and filters.
- For each republication group: the ids of its copies.

**Harness**

- A small interface: `search(query, filters, k)` and `match(document)`. Each implementation, including the reference ones, is an adapter.
- Metrics: precision@k, recall@k, MRR, nDCG for search; precision and recall of matches for subscriptions; p50, p95 and p99 latency; throughput.
- A report in plain text and JSON, stable across runs for the same seed, so a diff shows a regression.

## Milestones

1. Document model, topics and templates for the gazette profile; byte-identical output for the same seed.
2. Paraphrase vocabularies, distractors and republication.
3. Queries, subscriptions and the truth file.
4. Harness with the metrics and an adapter for the current PostgreSQL search.
5. Tender profile and a scale run at 1,000,000 fragments.

## Success criteria

- The same seed produces the same corpus and truth file, byte for byte.
- The metric code is tested against hand-computed values.
- A lexical-only baseline scores clearly below a perfect oracle on the paraphrase queries, which shows the corpus is not trivially solvable.
- Generating 1,000,000 fragments takes minutes, not hours, on a laptop CPU.

## Status

Implemented. Not marked as done yet: `pytest -m slow` and `pytest -m docker` have not been run, because the machine had neither the model nor Docker.

| Criterion | Result | Test |
|---|---|---|
| Same seed, same files | Met, also with a different `PYTHONHASHSEED` | `tests/synthetic/test_corpus.py::test_same_seed_writes_identical_files`, `::test_output_does_not_depend_on_the_process_hash_seed` |
| Metrics against hand-computed values | Met | `tests/benchmark/test_metrics.py` |
| Lexical baseline below the oracle on paraphrases | Met: recall@50 0.23 against 1.00, ndcg@10 0.05 against 1.00 | `tests/benchmark/test_harness.py::test_lexical_baseline_is_clearly_below_the_oracle_on_paraphrase_queries` |
| 1,000,000 fragments in minutes | Met: 1.7 minutes | `tests/synthetic/test_corpus.py::test_generation_speed_allows_a_million_fragments_in_minutes` (guard of 20 minutes) |

### First numbers

Gazette profile, seed 42, 2,000 documents, 164 topics, 120 queries, 60 subscriptions. Hashed provider, dimension 1024, synonym coverage 0.8, match threshold 0.45. Four virtual CPUs, Intel Xeon at 2.60 GHz, 15 GB, PostgreSQL 16 with pgvector 0.8.5 on the same machine.

| System | Queries | MRR | nDCG@10 | recall@50 | p50 |
|---|---|---|---|---|---|
| oracle | paraphrase | 1.00 | 1.00 | 1.00 | |
| lexical BM25 | paraphrase | 0.11 | 0.05 | 0.23 | 0.4 ms |
| lexical BM25 | same vocabulary | 0.82 | 0.62 | 0.57 | |
| exact vector scan | paraphrase | 0.86 | 0.74 | 0.88 | 2 ms |
| exact vector scan | same vocabulary | 0.91 | 0.80 | 0.92 | |
| PostgreSQL, all | paraphrase | 0.86 | 0.74 | 0.88 | 453 ms |
| PostgreSQL, semantic | paraphrase | 0.80 | 0.63 | 0.60 | 462 ms |

| Matching | Precision | Recall | Documents per second |
|---|---|---|---|
| brute force | 0.37 | 0.71 | 1146 |
| PostgreSQL | 0.37 | 0.71 | 3.4 |

- PostgreSQL in `all` mode finds the same as the exact scan, and its matching agrees with the brute-force one match by match (374 hits, 632 false positives, 156 misses). The adapters and the references confirm each other.
- `semantic` is below `all` because of the threshold. `hybrid` adds nothing on paraphrases: its full-text half requires every word of the query.
- Matching takes 0.28 s per document with 60 subscriptions, so the current design is what plan 3 says it is. A PostgreSQL search takes 0.45 s with 2,000 documents when asked for 50 of them.
- Matching precision is low because documents on the same kind and subject with another aspect count as wrong.

### Scale run

868,000 documents, 1,000,536 fragments, 3,180 topics, same seed and provider. Generation took 1.7 minutes and embedding 6.5, and the whole command 16 minutes with a peak of about 6.6 GB. Other tests were running on the machine at the same time.

| System | Queries | MRR | nDCG@10 | precision@10 | p50 |
|---|---|---|---|---|---|
| oracle | paraphrase | 1.00 | 1.00 | 1.00 | |
| lexical BM25 | paraphrase | 0.00 | 0.00 | 0.00 | 17 ms |
| lexical BM25 | same vocabulary | 0.99 | 0.93 | 0.88 | |
| exact vector scan | paraphrase | 0.56 | 0.51 | 0.49 | 498 ms |
| exact vector scan | same vocabulary | 0.95 | 0.85 | 0.79 | |

A topic has some 270 documents at this size, so recall@50 cannot pass 0.34 even for the oracle: precision and nDCG are the figures to read. PostgreSQL was not measured at this size, as loading it through the ingestion path would take days with subscriptions.

## Decisions

- **Topics and vocabularies.** 101 concepts with three vocabularies each give 3,180 topics, in five families. A corpus uses about 12 documents per topic until all pairs of kind and subject are in use, and then more aspects. Rankings are not trivial at any size measured: the exact vector scan has nDCG@10 of 0.75 on paraphrases with 400 documents and 0.50 with 8,000; lexical search has 0.18 and 0.00.
- **Language.** Spanish only, like the sources.
- **Where corpora live.** Generated on demand. `benchmark-output/` is ignored by git.
- **Held-out vocabulary.** For each kind and subject, one vocabulary is never used to name them in its documents, and is the only one its paraphrase queries use. The aspect is not held out, which leaves lexical search a weak signal.
- **Grades.** 2 for the exact topic, 1 for the same kind and subject with another aspect. Precision, recall and MRR count only grade 2.
- **Truth filters** are evaluated by code of their own, so the filters of the engine are not checked against themselves.
