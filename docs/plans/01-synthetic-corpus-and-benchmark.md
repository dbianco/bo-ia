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

## Open decisions

- How many topics and vocabularies are needed before rankings stop being trivial.
- Whether the generated text is Spanish only, matching the real sources.
- Where generated corpora live: generated on demand, never committed.
