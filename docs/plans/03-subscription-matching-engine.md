# 3. Subscription matching engine

## Goal

When a document is ingested, find the subscriptions it matches without scanning all of them. The stored items are queries and the incoming item is a document: a reverse search, with filters.

## Why

Monitoring is what sets ContextCrawl apart from a search application, and it is the part of the current design that stops scaling first.

## Current state

`evaluar_documento` in `backend/src/subscriptions/evaluator.py` runs synchronously inside ingestion. For every active subscription it:

1. checks the subscription's filters against the document metadata in Python;
2. runs one SQL query for the smallest cosine distance between the subscription's embedding and the document's fragments;
3. compares the score with a single global threshold (`SIMILARITY_THRESHOLD`, default 0.5);
4. records an `EvaluacionMatch` and creates its notification deliveries.

Cost per document grows linearly with the number of subscriptions, with one database round trip each, and ingestion waits for all of it.

## Design

**Index over subscriptions**

- A vector index (HNSW) holding one vector per active subscription.
- A filter index: for each filter key and value, the set of subscriptions that require it, plus the set that puts no condition on that key. Range filters (such as an amount) use an interval structure.
- A document is matched by: computing the set of subscriptions whose filters it satisfies, then searching the vector index from each of its fragments, restricted to that set, and keeping subscriptions whose best score reaches the threshold.

**The hard parts**

- **Threshold search, not top-k.** The question is "every subscription above the threshold", which has no fixed result size. The traversal has to keep expanding while it still finds results above the threshold, and stop safely.
- **Filters invert.** In ordinary search the query carries the filter and the documents carry metadata. Here each stored subscription carries its own filter and the document carries the metadata.
- **Selective filters.** When few subscriptions pass the filter, graph traversal degrades; below a cut-off the engine should scan that small set exactly.
- **Many fragments per document.** A document matches if any fragment does; searching per fragment must not multiply the cost needlessly.
- **Churn.** Subscriptions are created, paused, resumed and deleted while documents arrive.

**Integration**

- The engine sits behind an interface with two implementations: the current loop (the reference) and the indexed one.
- Matching moves out of the ingestion transaction into a queue processed after the document is committed, so a slow match never blocks ingestion.
- The per-subscription fields the current code maintains (`ultima_evaluacion`, at most one match per pair) keep their meaning; how `ultima_evaluacion` is updated without touching every row is an open decision below.

## Milestones

1. Extract the current loop behind an interface and add it to the benchmark harness as the reference.
2. Filter index with exact results and its own tests, including range filters.
3. Vector index over subscriptions with threshold search, no filters.
4. Filtered threshold search, with the exact-scan fallback for selective filters.
5. Updates: add, pause, resume and delete without rebuilding.
6. Asynchronous matching after ingestion, with the same records and notifications as today.

## Success criteria

Measured on the synthetic corpus from plan 1, against the brute-force reference:

- Match recall of at least 0.99 and precision of 1.0 (a reported match always truly passes the filter and the threshold).
- Proposed scale: 1,000,000 subscriptions, documents of 20 fragments.
- Proposed speed: at least 100 times the documents per second of the reference at that scale.
- Property tests: for random small sets of subscriptions and documents, the indexed engine and the reference return the same matches.
- After any sequence of add, pause, resume and delete, results equal those of an index rebuilt from scratch.

## Open decisions

- Whether the threshold stays global or becomes a property of each subscription. Per-subscription thresholds make the search harder and the product better.
- How to keep `ultima_evaluacion` meaningful when most subscriptions are never visited for a given document.
- Whether the index lives in the backend process or in a separate worker.
- Persistence and recovery of the index: see plan 5.
