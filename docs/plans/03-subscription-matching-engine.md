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

## Status

Implemented. Not marked as done yet: `pytest -m slow` and `pytest -m docker` have not been run, because the machine had neither the model nor Docker.

| Criterion | Result | Test |
|---|---|---|
| Recall of at least 0.99 | Met: 0.9934 at 1,000,000 subscriptions | `tests/benchmark/test_scale_matching.py::test_the_engine_meets_the_criteria_against_brute_force`, `tests/matching/test_subscription_index.py::test_recall_and_precision_with_a_graph_and_long_documents` |
| Precision of 1.0 | Met | the same tests, `tests/matching/test_queue.py::test_a_reported_match_is_checked_against_the_filter` |
| 1,000,000 subscriptions, documents of 20 fragments | Measured at that scale | `python -m src.benchmark scale-matching` |
| At least 100 times the reference | Met: 34,600 times the loop the service used, with one query per subscription (extrapolated from 2,000 subscriptions). The owner confirmed that this is the reference that was meant. For information, 67 times a loop in memory, which did not exist | `scale-matching --database-url` |
| Random sets give the same matches as the reference | Met, exactly, with and without graph | `tests/matching/test_subscription_index.py::test_random_subscriptions_and_documents_match_as_in_the_reference`, `tests/matching/test_matchers.py::test_random_histories_give_the_same_matches` |
| Any sequence of changes equals an index built from scratch | Met on sets of up to 80 subscriptions, where the search visits everything. On a large graph both are approximate and need not miss the same ones | `tests/matching/test_subscription_index.py::test_any_sequence_of_changes_equals_an_index_built_from_scratch` |

### Numbers

Gazette profile, seed 42, 1,000,000 subscriptions drawn from 3,180 topics, 60% with filters; 30 documents of 20 fragments on different topics, with 6,800 matches each on average. Hashed provider, dimension 1024, synonym coverage 0.8, threshold 0.45. Four virtual CPUs, Intel Xeon (Ice Lake) at 2.60 GHz, 15 GB, PostgreSQL 16 with pgvector 0.8.5 on the same machine.

| | p50 per document | p95 |
|---|---|---|
| Indexed engine | 75 ms | 106 ms |
| Exact scan of the subscriptions that pass the filters, in memory | 559 ms | 740 ms |
| Loop in memory, one subscription after another | 5.1 s | 5.3 s |
| Loop with a query per subscription (extrapolated) | 2,636 s | |

Building the index takes 9 minutes. Recall is against the exact scan, which agrees with the loop in memory on the documents on which both ran.

## Decisions

- **Threshold.** Still global. The engine takes it with each document, so a threshold per subscription needs no new index; it comes with the strictness levels of plan 12, which is what makes it useful.
- **`ultima_evaluacion`.** A document is matched against every active subscription, so one row (`matching_state`) has the time of the last one. For an active subscription the attribute is computed from it and from when it became active; pausing freezes it (a trigger). No subscription row is written.
- **Where it lives.** In the backend process. The queue is in PostgreSQL, so a separate worker is possible later.
- **Persistence.** None: the index is built from PostgreSQL with the first document after a start. Plan 5.
- **Keeping it current.** Each change to a subscription records its transaction (a trigger), and the index asks for the ones that had not finished when it last looked. A change that commits late is not missed, whoever makes it. Deletions are noticed when a match is recorded: the rows decide, not the index.
- **Few subscriptions.** Under 20,000 there is no graph: every subscription that passes the filters is compared, and results are exact. The same when the filters leave few.
- **Finding separate regions.** A plain graph search found only 0.73 to 0.92 of the matches at 200,000 subscriptions: the ones above the threshold are in several groups far from each other. The search first explores the layer above, which has one row in 16, and enters the lowest layer from everything near the threshold there.
- **Queue.** `matching_queue`, written in the transaction that completes the document. A worker takes a document with a lease of 5 minutes, retries failures with increasing waits of up to an hour, and processing a document twice adds nothing. Ingestion no longer sends email. Sending with retries is plan 10.
- **Downgrading** the migration drops the queue: let it drain first.
