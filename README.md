# ContextCrawl

[![CI](https://github.com/dbianco/ContextCrawl/actions/workflows/ci.yml/badge.svg)](https://github.com/dbianco/ContextCrawl/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

ContextCrawl is a semantic search and monitoring engine for sources that publish documents on a regular basis. It collects new documents from each source, lets people search them by meaning rather than exact words, and alerts subscribers when something relevant to them is published.

## What ContextCrawl is

Official gazettes, public tender portals and similar sources publish hundreds of notices a day, as PDFs or open datasets, with little more than a date to search by. Finding what matters means reading them every day, and a keyword search misses any notice worded differently from the query.

ContextCrawl started as a semantic search over the Boletín Oficial (official gazette) of the Province of Córdoba, Argentina, and grew into one shared engine that runs independent thematic installations. Each installation covers one subject area, with its own sources, filters, database and users.

### What it does

- **Collects documents on a schedule.** A connector per source fetches new publications and turns them into a common document format. The engine knows nothing about a source's HTML, PDFs or APIs.
- **Indexes them for search by meaning.** Each document is split into fragments and embedded locally with `Qwen/Qwen3-Embedding-0.6B`, stored in PostgreSQL with pgvector. Adding documents never requires retraining a model.
- **Splits gazette issues into notices.** A section of the Córdoba gazette is one PDF with many unrelated notices. Each one is a document of its own, with its notice number and pages.
- **Searches by meaning.** Semantic search with a similarity threshold is the default; a hybrid mode fuses it with full-text search. Results can be narrowed by date and by the filters the installation declares, and every result keeps its original text and source URL, with the notice number and page where the source has them.
- **Monitors on behalf of users.** A user saves a search as a subscription. Every new document is matched against the active subscriptions right after it is ingested, in the background, and a match is recorded with its score.
- **Notifies.** Each match is delivered to the user's inbox in the app and, optionally, by email.
- **Collects feedback.** Users can rate a result with a thumbs up or down.

### One engine, several installations

A new subject area is added through configuration plus connectors, not by forking the engine. An `installation.yaml` file names the installation and declares its sources and search filters; only a genuinely new kind of source needs code, in the form of a connector.

Two installations run today from the same code:

| Installation | Sources | Filters |
|---|---|---|
| **Boletines Córdoba** | Boletín Oficial of the Province of Córdoba (daily PDFs, five sections), plus municipal gazettes loaded manually | province, municipality |
| **Licitaciones Argentina** | National tenders from the comprar.gob.ar open dataset, and the procurement section of the Córdoba gazette | contracting body, estimated amount |

Each installation is deployed on its own, with its own database, which keeps subject areas isolated without multi-tenancy; within an installation there are multiple users. Case law is a third use case the design anticipates, but it has not been built.

### Current state

The backend covers the full cycle: scheduled ingestion, search, accounts, subscriptions and notifications. The web UI covers search and result feedback only; accounts and subscriptions are managed through the API for now. Failed email deliveries are not retried automatically. ContextCrawl presents documents as searchable, traceable sources and does not replace the original publication or constitute legal advice.

## Documentation

The specs and design documents linked below are written in Spanish.

- **Feature plans:** [docs/plans/](docs/plans/README.md) — plans for the next features and the fixes for known defects (in English), with a recommended order and how to judge completion.
- **Platform spec:** [docs/design/2026-09-18-plataforma-tematica-reutilizable-design.md](docs/design/2026-09-18-plataforma-tematica-reutilizable-design.md) — motivation, architectural decisions and the detailed design of Etapa 1 (section 8).
- **Original MVP feature (spec-kit / SDD):** [docs/specs/construir-el-mvp-de-busqueda-semantica-del-bolet/](docs/specs/construir-el-mvp-de-busqueda-semantica-del-bolet/) — spec, plan, tasks and verification evidence for the Boletín vertical before it was generalized.
- **Etapa 1 feature (spec-kit / SDD):** [docs/specs/etapa-1-nucleo-generico-documento/](docs/specs/etapa-1-nucleo-generico-documento/) — generalization of the core (`Documento`, `fuentes`, `installation.yaml`, declared filters).
- **Etapa 2 feature (spec-kit / SDD):** [docs/specs/etapa-2-ingesta-operativa/](docs/specs/etapa-2-ingesta-operativa/) — scheduler, connector interface, `EjecucionFuente` and the first real connector (BOP Córdoba, Scrapy + PDF).
- **Etapa 3 feature (spec-kit / SDD):** [docs/specs/etapa-3-clientes-suscripciones/](docs/specs/etapa-3-clientes-suscripciones/) — session-based authentication, subscriptions and synchronous evaluation of new documents.
- **Etapa 4 feature (spec-kit / SDD):** [docs/specs/etapa-4-notificaciones/](docs/specs/etapa-4-notificaciones/) — notification delivery (internal inbox, email over SMTP).
- **Etapa 5 feature (spec-kit / SDD):** [docs/specs/etapa-5-segundo-vertical/](docs/specs/etapa-5-segundo-vertical/) — second vertical (Argentine public tenders, "licitaciones"), two new connectors and a second real installation running in parallel.
- **Accessibility checklist:** [docs/accessibility-checklist.md](docs/accessibility-checklist.md) (WCAG 2.1 AA).

## Clients and subscriptions (Etapa 3)

Authentication uses sessions with an HttpOnly cookie (`sesiones` table, no JWT). `GET /v1/search` and `GET /v1/config` remain public; only managing subscriptions requires an account. The web UI has no login screens yet, so test it with `curl`/`httpx` and a saved cookie:

```bash
curl -c cookies.txt -X POST http://localhost:9101/v1/auth/registro \
  -H 'content-type: application/json' -d '{"email": "cliente@example.org", "password": "a-long-password"}'
curl -b cookies.txt -c cookies.txt -X POST http://localhost:9101/v1/auth/login \
  -H 'content-type: application/json' -d '{"email": "cliente@example.org", "password": "a-long-password"}'
curl -b cookies.txt -X POST http://localhost:9101/v1/suscripciones \
  -H 'content-type: application/json' \
  -d '{"texto_busqueda": "licitaciones de obra vial", "filtros": {"municipio": "Carlos Paz"}}'
```

When the ingestion of a genuinely new document finishes, the document is left in a queue (`matching_queue`), in the same transaction. A background thread of the backend matches it: it finds the subscriptions whose filters the document passes and whose embedding is close enough to one of its fragments. A match is recorded in `evaluaciones_match` with its score, applied filters and date, and triggers its notifications (Etapa 4, see below). A failure is retried later and does not stop other documents.

The subscriptions are in an index in memory, kept current from the database, so a document is not compared with each of them ([numbers](docs/plans/03-subscription-matching-engine.md#numbers)). `MATCHING_ENGINE=loop` goes back to one query per subscription.

## Notifications (Etapa 4)

Each match creates one `EntregaNotificacion` per channel declared on the subscription (`canales: ["bandeja", "correo"]` when creating it; the default is `"bandeja"` only). `"bandeja"` (inbox) is delivered immediately — it is just a row you can query through the API. `"correo"` (email) attempts a real SMTP send, configured entirely through environment variables (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` in `.env.example`); if SMTP is not configured or the send fails, the delivery is marked `fallida` with the reason, without interrupting ingestion or the rest of the evaluation.

**No automatic retry yet**: a failed delivery is not retried on its own (gap documented in `docs/specs/etapa-4-notificaciones/spec.md`).

```bash
curl -b cookies.txt -X POST http://localhost:9101/v1/suscripciones \
  -H 'content-type: application/json' \
  -d '{"texto_busqueda": "licitaciones de obra vial", "filtros": {}, "canales": ["bandeja", "correo"]}'
curl -b cookies.txt http://localhost:9101/v1/notificaciones   # your own notification inbox
```

## Installation configuration

`config/installation.yaml` defines the installation name, the initial sources (with their connector, if any) and the filters the search exposes — see `INSTALLATION_CONFIG` in `.env.example`. Adding a new source or filter does not require touching the engine.

### Operational ingestion (Etapa 2)

A source can declare a `conector` block in `installation.yaml`:

```yaml
fuentes:
  - clave: cordoba-provincial
    nombre: Boletín Oficial de la Provincia de Córdoba
    conector:
      tipo: boletin-cba-pdf-diario   # key registered in backend/src/connectors/registry.py
      frecuencia_minutos: 1440       # once a day
      config:
        url_template: "https://boletinoficial.cba.gov.ar/wp-content/4p96humuzp/{anio}/{mes}/{seccion}_Secc_{ddmmyy}.pdf"
        secciones: [1, 2, 3, 4, 5]
    metadata:                        # optional: added to every document of the source
      provincia: Córdoba
```

`metadata` holds values that are the same for the whole source, so that the declared filters find its documents. At startup, a declared filter that no source can fill is logged as a warning. Changing it affects new documents; `python -m src.commands.resegment` adds it to the stored ones (see below).

The scheduler runs **inside the same `backend` container** (it is not a separate service): on startup it schedules one job per source that has a connector, according to its `frecuencia_minutos`. Each run is recorded in `ejecuciones_fuente` (start, end, discovered, new, existing, errors). A source with no `conector` declared is still fed only by the seed or by a manual `POST /v1/documentos`, as in Etapa 1.

To trigger a run without waiting for the scheduler:

```bash
curl -X POST http://localhost:9101/v1/fuentes/cordoba-provincial/ejecutar
```

Connectors available today (`backend/src/connectors/registry.py`):

| Key (`tipo`) | What it does |
|---|---|
| `boletin-cba-pdf-diario` | Direct HTTP (`curl`, see Etapa 5) against `boletinoficial.cba.gov.ar`: predictable PDF URL per section/date, extracts text with `pypdf` and splits it at the closing line of each notice. One `DocumentoNormalizado` per notice, with its number, pages and issue. The cover is kept but not searchable, and text without a closing line is one "unsegmented" document. |
| `comprar-gob-ar-csv` | Streams the open dataset of national tenders (`Convocatorias.csv`, datos.gob.ar) and produces one `DocumentoNormalizado` per row, filtered by `anio_desde` (Etapa 5). |
| `bop-cordoba-scrapy` | Scrapy + PDF extraction against the official gazette of the Diputación de Córdoba, **Spain** (`bop.dipucordoba.es`) — the reference connector from Etapa 2, unused by any installation since Etapa 5 (it pointed at the wrong site by mistake; see `docs/specs/etapa-5-segundo-vertical/`). It stays registered and tested, so already-proven code is not deleted. |

Notices that the gazette prints as an image have no text to extract: only their closing line is stored. `municipio` is read from the title of municipal notices. `organismo` and `monto` are not read from gazette notices yet ([plan 8](docs/plans/08-classification-and-field-extraction.md)), so filtering by them excludes those.

#### Upgrading an installation with stored gazette sections

Before the notices were split, a whole section was one document. After upgrading, split the stored ones, or the next run for the same day adds its notices next to them:

```bash
docker compose exec backend python -m src.commands.resegment --source cordoba-provincial --dry-run
docker compose exec backend python -m src.commands.resegment --source cordoba-provincial --refetch
```

`--refetch` downloads each PDF again to know the pages, and uses the saved text when it cannot; without it the notices have no page. Choose it on the first run: a section that has been split is not split again. It raises no alerts, keeps the matches and ratings of the replaced sections, and can be run again if it is interrupted.

Each connector's tests run against local fixtures; tests marked `live` (excluded by default and from CI) run against the real site/dataset.

Endpoints exposed by the backend (`http://localhost:9101`):

| Method and path | What it does |
|---|---|
| `GET /v1/search` | Semantic search (`q`, `date_from`, `date_to`, `limit`, `mode`, `filtro.<key>` for each declared filter) |
| `GET /v1/issues/{source}/{issue}` | The documents of one issue, together (for example `cordoba-provincial/4_Secc_240926`) |
| `GET /v1/config` | Installation name and the filters declared in `installation.yaml` |
| `POST /v1/documentos` | Ingests a document (validates, chunks, generates embeddings) |
| `POST /v1/fuentes/{clave}/ejecutar` | Triggers a manual run of a source's connector |
| `POST /v1/valoraciones` | Records a thumbs up/down on a result |
| `POST /v1/auth/registro` | Creates an account (email + password) |
| `POST /v1/auth/login` | Logs in, sets the `contextcrawl_sesion` cookie |
| `POST /v1/auth/logout` | Ends the current session |
| `POST /v1/suscripciones` | Creates a subscription of your own (requires a session) |
| `GET /v1/suscripciones` | Lists your own subscriptions (requires a session) |
| `POST /v1/suscripciones/{id}/pausar` | Pauses one of your subscriptions |
| `POST /v1/suscripciones/{id}/reanudar` | Resumes one of your subscriptions |
| `DELETE /v1/suscripciones/{id}` | Deletes one of your subscriptions |
| `GET /v1/notificaciones` | Your own notification inbox (requires a session) |
| `GET /health` | Health check |

## Second vertical: Argentine public tenders (Etapa 5)

`config/installation-licitaciones.yaml` is a second real installation, "Licitaciones Argentina", which validates that the engine is reusable without copying code: it declares its own sources (`comprar-ar-nacional`, `cba-provincial-licitaciones`) and its own filters (`organismo`, `monto`) without touching `src/`. It runs as a **second, complete Docker Compose stack in parallel** with the gazette one, with its own database and its own ports:

```bash
cp .env.licitaciones.example .env.licitaciones   # review/adjust ports and POSTGRES_DB if needed
docker compose -p bo-ia-licitaciones --env-file .env.licitaciones \
  -f docker-compose.yml -f docker-compose.licitaciones.override.yml \
  up -d --build
```

The override only replaces the volume that mounts `installation.yaml` with `installation-licitaciones.yaml`; it does not duplicate `docker-compose.yml`. By default it runs in the 9300 port range (backend at `http://localhost:9301`), independent of the gazette stack (9100).

An installation without the Boletín sample data declares `seed: false` in its `installation.yaml` — without this flag, `sembrar_si_vacio` (designed for the original installation) loads its sample data into any new installation with an empty database, regardless of the configuration (a real bug found and fixed in Etapa 5).

`comprar-gob-ar-csv` accepts `limite_filas` to cap how many CSV rows are processed per run — known gap: with no cursor, it always sees the same first N rows that match `anio_desde` and never the following ones (permanently partial coverage if used; see `docs/specs/etapa-5-segundo-vertical/verify-evidence.md`).

## Repository structure

- `backend/` — Ingestor, Processor and API (Python/FastAPI), consolidated into a single service. See `backend/src/` (code) and `backend/tests/` (tests).
- `web/` — search UI (Jinja2 + htmx).
- `config/` — one installation file per thematic installation.
- `docs/` — documentation: `plans/` (upcoming features), `specs/` (spec-kit artifacts for the SDD phase workflow), `design/` (design specs) and `reports/` (research reports and proofs of concept).

## Running locally

Requires Docker and Docker Compose (Docker Desktop on macOS or Windows).

```bash
cp .env.example .env
docker compose up --build
```

This starts three services: `db` (PostgreSQL + pgvector, port 9100), `backend` (Ingestor + Processor + API, port 9101) and `web` (search UI, port 9102). The ports sit in the 9100 range to avoid clashing with other apps running on the machine.

On startup, the backend runs the Alembic migrations, applies `installation.yaml` (creating the declared sources) and loads a handful of sample documents if the database is empty. The first run downloads the embedding model (`Qwen/Qwen3-Embedding-0.6B`, ~1 GB) and caches it in a volume; later startups are instant.

Open `http://localhost:9102` to use the UI, or try the API directly:

```bash
curl http://localhost:9101/health
curl "http://localhost:9101/v1/search?q=presupuesto+provincial"
```

### Without the model

`EMBEDDING_PROVIDER=hashed` replaces the real model with offline vectors, for development on a machine without network: texts are close if they share words. `EMBEDDING_PROVIDER=precomputed` replays vectors from a file (`EMBEDDING_PRECOMPUTED`). The vectors of two providers cannot be compared, so do not change it on a database that already has documents. The hashed vectors also need a lower `SIMILARITY_THRESHOLD` than the real model.

## Search engine

`SEARCH_ENGINE` chooses who answers searches. `postgres` (the default) uses pgvector and PostgreSQL full-text search. `engine` uses an engine in the backend process: BM25, a vector index with filters applied during the search, and the same fusion. The response is the same. The engine is built from the database at every start, and PostgreSQL answers until it is ready; it takes about 5.5 GB per million fragments ([numbers](docs/plans/04-hybrid-ranking-engine.md#numbers)). `RRF_WEIGHTS` sets the weights of the vector and text rankings.

## Benchmark

`python -m src.benchmark` generates a corpus with known answers and measures search and matching against it, with no database, network or model. See [how to run it](docs/plans/README.md#automated-checks) and the [first numbers](docs/plans/01-synthetic-corpus-and-benchmark.md#first-numbers).

## Running the tests

With Python 3.12 and the `db` service up (`docker compose up -d db`):

```bash
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export DATABASE_URL="postgresql+psycopg://bo_ia:dev_only_change_me@localhost:9100/bo_ia"

.venv/bin/pytest -m "not slow and not docker and not live"   # fast, with fake embeddings
.venv/bin/pytest -m slow                                     # downloads and uses the real model (~1 GB)
.venv/bin/pytest -m docker                                   # smoke test: brings everything up with docker compose
.venv/bin/pytest -m live                                     # BOP connector against the real site
```

The CI workflow (`.github/workflows/ci.yml`) runs the first two groups (no `docker` or `live`) in one job and the smoke test in another, on every push and pull request to `main`.

## License

Released under the [MIT License](LICENSE).
