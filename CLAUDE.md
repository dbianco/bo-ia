# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ContextCrawl is a semantic search and monitoring engine for sources that publish documents regularly (official gazettes, tender portals). One engine runs several independent installations, each with its own sources, filters, database and users. A new subject area is added through configuration plus connectors, not by forking the engine.

- `backend/`: Python 3.12, FastAPI, SQLAlchemy, PostgreSQL + pgvector. Ingestion, search, scheduler, subscriptions and notifications all run in one service.
- `web/`: separate Jinja2 + htmx app that only talks to the backend over HTTP. It covers search and result feedback, not accounts or subscriptions. It has no tests, no `pyproject.toml` (dependencies are listed in its Dockerfile) and is not linted in CI.

## Language

Existing identifiers, comments, API paths, DB tables, log messages and test names are mostly in Spanish. New source code is written in English (see the user's global instructions). Do not rename existing Spanish names, endpoints or columns as a side effect of another change. Specs and design docs under `docs/specs/`, `docs/design/` and `docs/reports/` are in Spanish. `README.md` and `docs/plans/` are in English.

## Commands

Tests need the `db` service (a real pgvector PostgreSQL; there is no SQLite fallback):

```bash
cp .env.example .env              # once
docker compose up -d db           # from the repo root, port 9100

cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # once
export DATABASE_URL="postgresql+psycopg://bo_ia:dev_only_change_me@localhost:9100/bo_ia"

.venv/bin/pytest -m "not slow and not docker and not live"       # fast suite
.venv/bin/pytest tests/api/test_search.py                       # one file
.venv/bin/pytest tests/api/test_search.py::test_name            # one test (or -k <expr>)
.venv/bin/ruff check src tests                                  # lint, as in CI
```

Test markers:

- `slow`: loads the real embedding model (about 1 GB download).
- `docker`: end-to-end smoke test on ports 9101/9102. It runs `docker compose down` at the end, so it also stops a dev stack that is already running.
- `live`: calls real external sites. Excluded from CI.

CI runs `pytest -m "not docker and not live"` (so it includes `slow`), then a separate compose smoke job.

Full stack: `docker compose up --build` (db 9100, backend 9101, web 9102). Source is copied into the images, so code changes need `--build`. The `config/installation.yaml` file is mounted read-only and read once per process, so restart `backend` after editing it.

Second installation, in parallel on ports 93xx:

```bash
cp .env.licitaciones.example .env.licitaciones
docker compose -p bo-ia-licitaciones --env-file .env.licitaciones \
  -f docker-compose.yml -f docker-compose.licitaciones.override.yml up -d --build
```

Migrations: `alembic upgrade head` runs from `backend/entrypoint.sh` on every container start. To run Alembic by hand, run it from `backend/` with `DATABASE_URL` set.

## Architecture

### Ingestion pipeline

`ingerir_documento` (`backend/src/ingestor/contract.py`) is the only code path that persists, fragments and embeds documents. The `POST /v1/documentos` endpoint, the seed and connector runs all go through it with a `DocumentoNormalizado`.

- It commits several times by design. The document is committed before fragmenting, so a failure leaves it saved with `estado="error"`.
- Deduplication is by `(fuente, identificador_externo)`, then by content hash across all sources. Any existing row counts as already ingested, including one in `estado="error"`, so ingesting it again does not retry it.
- For each genuinely new complete document it calls `evaluar_documento` (`src/subscriptions/evaluator.py`), which calls `crear_entregas_para_match` (`src/notifications/dispatcher.py`). All of this is synchronous, including SMTP sends. A failed email is recorded as `fallida` and must not interrupt ingestion. There is no automatic retry.

### Connectors

A connector only discovers and normalizes (`src/connectors/protocol.py`). It yields `DocumentoNormalizado` or `ErrorDescubrimiento` and never touches the DB or embeddings. `ejecutar_conector` (`src/connectors/runner.py`) ingests the results and records an `EjecucionFuente`. A per-document error is counted and the run continues. An exception from the connector itself marks the run `fallida`.

A new connector must be added to both `CONECTORES` and `VERSIONES` in `src/connectors/registry.py`. `installation.yaml` refers to it by that `tipo` key. The in-process APScheduler (`src/scheduler/`) creates one job per source that has a `conector` block. `POST /v1/fuentes/{clave}/ejecutar` runs one manually.

`boletin-cba-pdf-diario` fetches with `curl` on purpose, because the site returns 403 to `urllib`. `bop-cordoba-scrapy` targets a gazette in Spain and no installation uses it. It stays registered and tested deliberately.

Connector tests use local files in `tests/fixtures/`. The `*_live.py` files are the network counterparts.

### Installation config

`INSTALLATION_CONFIG` points to a YAML file validated by `src/config/installation.py`. An invalid file stops startup. It declares the sources, the search filters (`seleccion` or `rango_numerico`) and `seed`. The sample data in `src/seed/` is specific to the Boletín, so other installations set `seed: false`.

Keep domain-specific vocabulary out of the engine. It belongs in config, connectors, `src/ingestor/adapters/` and seed data. Per-vertical fields live in the `documentos.metadata` JSONB column. The query instruction in `src/processor/embeddings.py` still mentions government bulletins.

`src/search/filters.py` has two implementations of the same filter semantics that must stay consistent:

- `aplicar_filtros` builds SQL for search.
- `cumple_filtros` is pure Python for subscription matching.

A subscription stores a snapshot of each filter's type and value, so later config changes do not alter how it is evaluated.

### Search

`buscar` in `src/api/search.py` over-fetches fragment candidates, then applies the threshold and then the limit. `SIMILARITY_THRESHOLD` is internal and not exposed in the API.

- `semantic` (default): vector results above the threshold.
- `hybrid`: vector and Spanish full-text results fused with RRF. A result without a text match still has to pass the threshold.
- `all`: the same fusion with no threshold.

Results are fragments, so one document can appear more than once. Subscription matching uses the same threshold against the best fragment of the new document.

### API wiring

Dependencies (`get_session`, `get_embedder`, `get_installation_config`, `get_usuario_actual`) live in `src/api/deps.py`. API tests replace them through `app.dependency_overrides` and use `FakeEmbeddingProvider` or a stub with fixed vectors. Fake vectors are hash-based, so their similarity carries no meaning. Use fixed vectors when a test depends on ranking or the threshold.

Authentication uses server-side sessions with an HttpOnly cookie. `GET /v1/search` and `GET /v1/config` are public.

### Database and tests

- The embedding dimension (1024) is defined in both `src/db/models.py` and `src/processor/embeddings.py`.
- Every migration needs a working downgrade. `tests/test_migrations.py` steps down a hardcoded number of revisions, so increase it when you add one.
- Indexes created by raw SQL in a migration are also declared on the model, to avoid `alembic check` drift.
- `tests/conftest.py` drops and recreates the `bo_ia_test` database. `test_migrations.py` uses the same name, so do not run two pytest sessions at once.
- Test isolation is by `TRUNCATE ... CASCADE`, because the code under test commits. Add a new table to that list if the cascade does not reach it.

## Workflow and plans

- The repo is registered with the SDD Orchestrator (`.sdd/config.json`, advisory `warn` mode). Follow the `sdd-workflow` skill. Past feature artifacts are in `docs/specs/<feature>/`.
- Planned features are in `docs/plans/` (start with its README). New benchmarks and tests for them must be offline (no network, GPU, Docker or model download), deterministic from a seed, based on generated data, and compared against a simple reference implementation.
