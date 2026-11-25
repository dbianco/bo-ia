# Feature plans

Plans for the next set of ContextCrawl features. They shift the centre of the project from assembling existing libraries to systems built here and measured against a reference.

Each plan states the goal, what the code does today, the design, milestones, and how success is checked. Numeric targets are proposals to confirm when the first benchmark numbers exist.

| # | Plan | Kind | Depends on |
|---|---|---|---|
| 1 | [Synthetic corpus and benchmark harness](01-synthetic-corpus-and-benchmark.md) | Foundation | — |
| 2 | [Offline embeddings](02-offline-embeddings.md) | Foundation | — |
| 3 | [Subscription matching engine](03-subscription-matching-engine.md) | Core system | 1, 2 |
| 4 | [Hybrid ranking engine](04-hybrid-ranking-engine.md) | Core system | 1, 2 |
| 5 | [Incremental, crash-safe index](05-incremental-crash-safe-index.md) | Extension | 3 or 4 |
| 6 | [Near-duplicate collapsing](06-near-duplicate-collapsing.md) | Extension | 1 |

## Recommended order

1. Plans 1 and 2 first. Every later plan is checked with the generated corpus and runs without a model download.
2. Plan 3 next. Monitoring is what sets ContextCrawl apart from a search app, and it is where the current design stops scaling.
3. Plan 4, then 5 and 6 as the indexes from 3 and 4 need them.

## Shared constraints

- **Offline by default.** Tests and benchmarks run with no network, no GPU, no Docker and no model download. PostgreSQL and the real embedding model stay available as a reference and for production use.
- **Deterministic.** A seed fixes the corpus, the vectors and the benchmark output, so two runs can be compared exactly.
- **A reference for every claim.** Each new system is measured against a simple implementation that is obviously correct (a brute-force loop or an exact scan), on recall first and speed second.
- **Generated data only.** Benchmarks use the synthetic corpus, never live sources or real personal data.
