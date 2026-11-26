# 2. Offline embeddings

## Goal

Embeddings that work with no network, no GPU and no model download, and that still place related texts near each other, so benchmarks on the synthetic corpus are meaningful.

## Why

- The production provider downloads `Qwen/Qwen3-Embedding-0.6B` (about 1 GB) on first run and is slow on CPU. A full-corpus benchmark with it is impractical, and impossible offline.
- The test provider hashes the whole text into a vector. Two texts that differ by one character get unrelated vectors, so it cannot be used to measure recall.

## Current state

- `backend/src/processor/embeddings.py` defines the `EmbeddingProvider` protocol (`embed_query`, `embed_passage`) with two implementations: `SentenceTransformerEmbeddingProvider` and `FakeEmbeddingProvider` (SHA-256 of the text, no notion of similarity).
- The vector size is fixed by `EMBEDDING_DIM` and by the `Vector(EMBEDDING_DIM)` columns in `backend/src/db/models.py`.

## Design

Three providers behind the existing protocol, chosen by configuration:

1. **Hashed-feature provider (new, default for tests and benchmarks).**
   - Tokenize, fold accents and case, take words and word pairs.
   - Hash each feature to a fixed pseudo-random direction (seeded) and sum them with a weight, then normalize.
   - Texts that share vocabulary end up close; texts that share none are near orthogonal.
   - Optional synonym table supplied by the corpus generator, so paraphrases of the same topic land near each other without the texts sharing words. This is what makes semantic search different from lexical search in the benchmark.
2. **Precomputed provider (new).** Reads vectors from a file keyed by a hash of the text. Lets a corpus be embedded once with the real model elsewhere and replayed offline.
3. **Model provider (existing).** Unchanged; used in production and as an optional reference.

The provider and its parameters are recorded in every benchmark report, since results from different providers are not comparable.

## Milestones

1. Hashed-feature provider with deterministic output and unit norm.
2. Synonym table support, fed by the corpus generator from plan 1.
3. Precomputed provider with a simple on-disk format and a clear error when a text is missing.
4. Provider selection through settings; the fake SHA-256 provider is removed or kept only for tests that need arbitrary vectors.

## Success criteria

- The fast test suite and the benchmark run with the network disabled and no model on disk.
- Same text, same seed: same vector across runs and machines.
- On the synthetic corpus, the nearest neighbours of a document are mostly from its own topic, measured as precision against the truth file.
- Embedding 1,000,000 fragments takes minutes on a laptop CPU.

## Status

Implemented. Not marked as done yet: the test of the real model (`pytest -m slow`) and `pytest -m docker` have not been run, because the machine had neither the model nor Docker. The model provider only gained a `describe` method.

| Criterion | Result | Test |
|---|---|---|
| Tests and benchmark with no network and no model | Met. The tests of plans 1 and 2 also pass in a network namespace without interfaces, where the database cannot be reached | `tests/benchmark/test_offline_embeddings.py::test_benchmark_command_runs_offline_and_names_the_provider` |
| Same text and seed, same vector | Met: sums are done on integers, and a recorded vector is checked. Only one machine was available | `tests/processor/test_hashed_embeddings.py::test_vector_is_the_same_on_every_machine` |
| Nearest neighbours mostly from the same topic | Met: precision@5 of 0.66 (gazette) and 0.55 (tenders), without counting republished copies | `tests/benchmark/test_offline_embeddings.py::test_nearest_neighbours_are_mostly_from_the_same_topic` |
| 1,000,000 fragments in minutes | Met: 6.5 minutes, one process | `tests/processor/test_hashed_embeddings.py::test_speed_allows_a_million_fragments_in_minutes` (guard of 20 minutes) |

## Decisions

- **Dimension.** `EMBEDDING_DIM` by default, so the schema does not change. In-process indexes may use a smaller one (`dim`, `--dim`).
- **Synonyms against shared words.** The provider knows 80% of the phrases of the corpus as synonyms (`--synonym-coverage`), with a weight of 3 for a concept, 1 for a word and 0.5 for a pair of words. They were chosen on seeds 1001 and 1002 with these measurements in mind (seed 42, 2,000 documents, recall@50 of the exact scan and precision@5 of the neighbours):

  | Coverage | Gazette: paraphrase | Gazette: neighbours | Tenders: paraphrase | Tenders: neighbours |
  |---|---|---|---|---|
  | 0 (words only) | 0.24 | 0.15 | 0.12 | 0.12 |
  | 0.4 | 0.47 | 0.44 | 0.32 | 0.32 |
  | 0.6 | 0.61 | 0.51 | 0.55 | 0.43 |
  | **0.8** | **0.88** | **0.66** | **0.77** | **0.55** |
  | 1 | 1.00 | 0.88 | 1.00 | 0.83 |

  With no synonyms the vectors are as blind to paraphrases as lexical search (0.24 and 0.23). With all of them every answer is given away, which is the circular case. At 0.8 search is clearly semantic and still fails on about one paraphrase in five.
- **What these numbers are not.** The synonyms come from the generator, so they say nothing about how well the real model understands Spanish. They serve to compare implementations of search and matching that receive the same vectors.
- **The fake provider** stays, only for tests that need arbitrary vectors. Settings cannot select it.
- **Match threshold.** 0.45 for the hashed provider in the benchmark. It is not comparable with `SIMILARITY_THRESHOLD` for the real model.
- **Selection.** `EMBEDDING_PROVIDER` (`model` by default, `hashed`, `precomputed`), `EMBEDDING_SEED`, `EMBEDDING_SYNONYMS` and `EMBEDDING_PRECOMPUTED`.
