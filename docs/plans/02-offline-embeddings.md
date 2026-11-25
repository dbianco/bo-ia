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

## Open decisions

- Dimension of the offline vectors: keep `EMBEDDING_DIM` so the database schema is unchanged, or allow a smaller one for in-process indexes.
- How much of the similarity structure comes from the synonym table versus shared words. Too much makes the benchmark circular; this needs a short written justification with the first numbers.
