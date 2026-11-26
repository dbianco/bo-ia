# Feature plans

Plans for the next set of ContextCrawl features. Plans 1–6 shift the centre of the project from assembling existing libraries to systems built here and measured against a reference. Plans 7–14 close gaps in what users get, found by reviewing the code, the companion project and what similar monitoring tools advertise. Plan 15 fixes the defects found in that review.

Each plan states the goal, what the code does today, the design, milestones, and how success is checked. Numeric targets are proposals to confirm when the first benchmark numbers exist.

| # | Plan | Kind | Depends on |
|---|---|---|---|
| 1 | [Synthetic corpus and benchmark harness - DONE](01-synthetic-corpus-and-benchmark.md) | Foundation | — |
| 2 | [Offline embeddings - DONE](02-offline-embeddings.md) | Foundation | — |
| 3 | [Subscription matching engine - DONE](03-subscription-matching-engine.md) | Core system | 1, 2 |
| 4 | [Hybrid ranking engine](04-hybrid-ranking-engine.md) | Core system | 1, 2 |
| 5 | [Incremental, crash-safe index](05-incremental-crash-safe-index.md) | Extension | 3 or 4 |
| 6 | [Near-duplicate collapsing](06-near-duplicate-collapsing.md) | Extension | 1 |
| 7 | [Notice segmentation and citable results](07-notice-segmentation.md) | Foundation | 1 |
| 8 | [Notice classification and field extraction](08-classification-and-field-extraction.md) | Product | 1, 7 |
| 9 | [Entity watchlists](09-entity-watchlists.md) | Product | 1, 7 |
| 10 | [Explained alerts, digests and reliable delivery - DONE](10-explained-alerts-and-digests.md) | Product | 7 |
| 11 | [Deadlines and amendments](11-deadlines-and-amendments.md) | Product | 1, 8, 10 |
| 12 | [Subscription preview and feedback-based tuning](12-feedback-based-tuning.md) | Product | 1, 2, 10 |
| 13 | [Source coverage and health](13-source-coverage-and-health.md) | Reliability | — |
| 14 | [Usage and operation statistics](14-usage-and-operation-statistics.md) | Product | — |
| 15 | [Fix known defects - DONE](15-known-defects.md) | Defects | — |

## Recommended order

1. Plan 15 first. It depends on nothing, and it closes the endpoints that anyone can use to add documents. Plans 7, 11 and 13 build on its smaller fixes.
2. Plans 1 and 2 next. Most later plans are checked with the generated corpus and run without a model download.
3. Plan 13 can start at any time after plan 15, alongside these. Until it is done, a missed day is not fetched later.
4. Plan 7 next. It changes what a document is, which affects matching, search, alerts and duplicates.
5. Plan 3. Monitoring is what sets ContextCrawl apart from a search app, and it is where the current design stops scaling.
6. Plan 10, then 8 and 9. Plan 7 multiplies the number of documents, so digests and explained alerts come before more ways to match.
7. Plan 4, then 5 and 6 as the indexes from 3 and 4 need them.
8. Plans 11 and 12 when their dependencies are in place. Plan 14 can start at any time with coverage and ingestion figures; its per-user views need the sign-in screens of plan 10.

## Shared constraints

- **Offline by default.** Tests and benchmarks run with no network, no GPU, no Docker and no model download. PostgreSQL and the real embedding model stay available as a reference and for production use.
- **Deterministic.** A seed fixes the corpus, the vectors and the benchmark output, so two runs can be compared exactly.
- **A reference for every claim.** Each new system is measured against a simple implementation that is obviously correct (a brute-force loop or an exact scan), on recall first and speed second.
- **Generated data only.** Benchmarks use the synthetic corpus, never live sources or real personal data.

## How to judge completion

A plan is complete only when every check below passes: the setup, the automated checks, the manual checks for that plan, and the pass rule. A milestone that is finished on its own does not complete a plan.

### Setup

For the existing test suite, from the repository root:

```bash
cp .env.example .env   # first time only
docker compose up -d db
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export DATABASE_URL="postgresql+psycopg://bo_ia:dev_only_change_me@localhost:9100/bo_ia"
```

The existing suite needs the database. The new tests and benchmarks of a plan follow the shared constraints: they must also run with the database stopped and the network off. Tests that compare against PostgreSQL, check a migration or exercise the API are the exception and belong to the existing suite.

### Automated checks

All must pass, from `backend/`:

- `.venv/bin/ruff check src tests`
- `.venv/bin/pytest -m "not docker and not live"`, which includes the tests that load the real model.
- `.venv/bin/pytest -m docker`, for any plan that changes dependencies, migrations, startup, the API or the web interface. It stops a running development stack when it ends.
- The plan's own tests. There is at least one test for each item under its **Success criteria**, and the pull request lists which test covers which item.
- The plan's benchmark, where a criterion is a measurement.

The benchmark command of plan 1, from `backend/`. It needs no database, no network and no model:

```bash
.venv/bin/python -m src.benchmark generate --profile gazette --seed 42 --documents 2000 --out benchmark-output/corpus
.venv/bin/python -m src.benchmark run      --profile gazette --seed 42 --documents 2000 --out benchmark-output/run
```

`generate` writes the documents, the truth file and the synonym table. `run` writes `report.txt` and `report.json`, which are identical between runs with the same arguments, and `timings.json`, which is not. To measure the PostgreSQL implementation, add `--systems` with any of `postgres-semantic`, `postgres-hybrid`, `postgres-all` and `postgres-match`, and `--database-url` with the server to use. They run in a database of their own, created and dropped by the command. `scale-matching` and `scale-search` are the scale runs of plans 3 and 4: by default a million subscriptions or fragments, some 20 minutes and 10 GB each. With `--database-url` they measure PostgreSQL too (`scale-search`, only it).

The PostgreSQL run of `scale-search` needs a server with several GB of shared memory to build its vector index: the 64 MB that Docker gives a container by default, as in `docker-compose.yml`, are not enough.

`--provider model` uses the real model, and `precompute` saves its vectors to replay them offline with `--provider precomputed`.

For every plan that adds a database migration, `tests/test_migrations.py` is updated so that the new downgrade is exercised.

### Manual checks

Each row is run on a freshly started stack by following only the repository's documentation.

| Plan | Check by hand |
|---|---|
| 1 | Generate a corpus twice with one seed and compare the files and truth files: they are identical. Run the benchmark twice: the quality figures match. Timings are reported separately and may differ. |
| 2 | With the network off and no model on disk, run the benchmark. It completes and names the embedding provider in its report. |
| 3 | Create subscriptions, ingest a matching and a non-matching document, and see one alert for the first only. Pause a subscription and ingest again: no alert. |
| 4 | Run the same queries, with and without filters, on both search implementations. The response format is the same, and the recall and latency curve is published. |
| 5 | Kill the process during ingestion, restart it, and search. Every acknowledged document is found and no deleted one returns. |
| 6 | Ingest one notice on three dates. A search shows it once with three dates, and a subscriber has one alert. |
| 7 | Ingest a real gazette section. Open five results and find each notice on the stated page of the PDF. Filter by a declared filter and get results. |
| 8 | Read twenty extracted values next to their source text. Filter by a notice type, with and without unclassified notices. |
| 9 | Watch a tax identifier, ingest a notice that writes it with separators and a line break, and see the alert highlight it. A longer number that contains it raises no alert. |
| 10 | Stop the mail server, ingest a matching document, start it again: the email arrives with an excerpt. Run a digest twice: it arrives once. The pause link works without signing in. |
| 11 | Follow a tender, ingest an amendment that moves its date, and see the change alert. The old reminder is gone and the calendar feed shows the new date. |
| 12 | Preview a subscription, save it, ingest the same period into a clean installation, and compare: the matches are the same. Accept a proposal, then undo it. |
| 13 | Block a source for a simulated week, then restore it. The missed days are recovered, and the source showed as broken in the meantime. |
| 14 | Compare each figure on the statistics pages with a direct database query. A normal user cannot open the operator view. |
| 15 | Post a document without a token and with a wrong one: both are rejected. Restart the backend with an overdue source and see it run. Filter by province and find collected gazette documents. |

### Pass rule

- Every automated check is green and the plan's manual check behaves as described.
- Each success criterion is met with its stated number. Where the number is a proposal, the first measurement and the confirmed target are written into the plan before the work is called complete. A target is never lowered without saying so and why.
- Every measurement states the corpus seed and size, the embedding provider and the machine.
- A criterion that was not checked is listed as not checked, with the reason. It does not count as passed.
- The plan's **Open decisions** are answered in the plan, or explicitly deferred with a reason.
- `README.md` and any other documentation the change affects are updated, and the plan's title is marked `- DONE`.
