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
- **Notifies.** Each match is delivered to the user's inbox in the app and, optionally, by email, at once or in a daily or weekly digest. An alert shows the excerpt that matched, where to find it and why. An email that fails is sent again.
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

The backend covers the full cycle: scheduled ingestion, search, accounts, subscriptions and notifications. The web UI covers search, result feedback, accounts, subscriptions and the inbox of alerts. Addresses are not verified when an account is created, and a password cannot be recovered yet. ContextCrawl presents documents as searchable, traceable sources and does not replace the original publication or constitute legal advice.

## Contents

- [Getting started](#getting-started): from nothing to a working installation
- [Configuration](#configuration): the `.env` file, the installation file, every variable
- [Everyday operation](#everyday-operation): documents, sources, logs, backups, upgrades
- [Using it](#using-it): search, accounts, subscriptions, alerts, the API
- [Development](#development): without Docker, tests, benchmark
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation): plans, specs and designs

## Getting started

You need Docker with Docker Compose (Docker Desktop on macOS or Windows), about 6 GB of disk and 4 GB of memory. The first start downloads the embedding model (about 1 GB).

**1. Create the `.env` file.** Everything is configured there. It is ignored by git: do not commit it.

```bash
cp .env.example .env
```

**2. Generate the two secrets**, and put each one in its line of `.env`. They are optional, but without them some things are closed:

```bash
openssl rand -hex 32   # OPERATOR_TOKEN=...  without it, documents cannot be added through the API
openssl rand -hex 32   # LINK_SECRET=...     without it, emails have no link to pause a subscription
```

Before exposing it to a network, also change `POSTGRES_PASSWORD` (and the same password inside `DATABASE_URL`). PostgreSQL only takes it when the database is created.

**3. Start it.**

```bash
docker compose up -d --build
docker compose ps          # wait until backend is "healthy"; the first time takes some minutes
docker compose logs -f backend
```

This starts three services. The backend applies the database migrations, creates the sources of `config/installation.yaml`, and loads some sample documents if the database is empty.

| Service | Address | What it is |
|---|---|---|
| `web` | `http://localhost:9102` | The web page |
| `backend` | `http://localhost:9101` | The API (interactive documentation in `/docs`), the scheduler and the background workers |
| `db` | `localhost:9100` | PostgreSQL with pgvector |

**4. Check that it works.**

```bash
curl http://localhost:9101/health
curl "http://localhost:9101/v1/search?q=presupuesto+provincial"
```

Open `http://localhost:9102`, search for something, create an account (**Crear cuenta**) and a subscription (**Suscripciones**).

**5. Add a document and see the alert.** Take the token from `.env` first:

```bash
export OPERATOR_TOKEN=$(grep ^OPERATOR_TOKEN= .env | cut -d= -f2)

curl -X POST http://localhost:9101/v1/documentos \
  -H "Authorization: Bearer $OPERATOR_TOKEN" -H 'content-type: application/json' \
  -d '{"fuente_clave": "carlos-paz-municipal", "identificador_externo": "ORD-1", "fecha": "2026-10-01",
       "texto": "Licitación para la pavimentación de calles del barrio norte.", "url_fuente": "https://example.org/ord-1"}'
```

If it matches your subscription it is in **Avisos** after a second or two.

**6. To send emails**, set the `SMTP_*` variables (see [Email](#email)) and apply them. A change in `.env` needs the containers to be created again; `docker compose restart` does not read it:

```bash
docker compose up -d
```

**To stop it:** `docker compose down`. The data stays in Docker volumes; `docker compose down -v` deletes it.

## Configuration

### The .env file

`docker compose` reads `.env` in the root of the repository. `.env.example` has every variable with its default. The second installation uses `.env.licitaciones` (see [below](#second-vertical-argentine-public-tenders-etapa-5)). A variable that is missing from your `.env` takes its default, so an older file keeps working after an upgrade.

A value that is not valid stops the backend at startup, with the name of the variable in the log.

#### Database

| Variable | Default | What it does |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `bo_ia`, `dev_only_change_me`, `bo_ia` | Created with the database, the first time |
| `POSTGRES_PORT` | `9100` | Port of the database on this machine |
| `DATABASE_URL` | | How the backend connects. It must have the same user, password and database; inside Docker the host is `db:5432` |

#### Services

| Variable | Default | What it does |
|---|---|---|
| `BACKEND_PORT`, `WEB_PORT` | `9101`, `9102` | Ports on this machine |
| `BACKEND_INTERNAL_URL` | `http://backend:8000` | Where the web finds the API |
| `INSTALLATION_CONFIG` | `/app/installation.yaml` | Installation file, inside the container |
| `PUBLIC_WEB_URL` | `http://localhost:9102` | Address of the web as its users see it. The emails link to it; if it is https, the session cookie is only sent over https |

#### Secrets

| Variable | Default | What it does |
|---|---|---|
| `OPERATOR_TOKEN` | empty | Required to add documents and to run a source through the API (see [Operator token](#operator-token)). **Empty: both are closed to everybody** |
| `LINK_SECRET` | empty | Signs the links to pause a subscription from an email. Empty: emails have no such link. Changing it cancels the links that were already sent |

#### Search and embeddings

| Variable | Default | What it does |
|---|---|---|
| `EMBEDDING_PROVIDER` | `model` | `model` is the real one; `hashed` works [without the model](#without-the-model); `precomputed` reads vectors from a file. Do not change it on a database with documents: the vectors of two providers cannot be compared |
| `EMBEDDING_MODEL`, `EMBEDDING_CACHE_DIR` | `Qwen/Qwen3-Embedding-0.6B`, `/model-cache` | The real model, and where it is kept |
| `EMBEDDING_SEED`, `EMBEDDING_SYNONYMS` | `0`, empty | Only for `hashed`: its seed, and a JSON file that maps each concept to a list of phrases |
| `EMBEDDING_PRECOMPUTED` | empty | Only for `precomputed`: the vector file |
| `SIMILARITY_THRESHOLD` | `0.5` | From 0 to 1. Below it, a result of a semantic search or a match is dropped. The hashed provider needs a lower one, such as 0.25 |
| `SEARCH_ENGINE` | `postgres` | Who answers searches: `postgres`, or `engine`, in the memory of the backend (see [Search engine](#search-engine)) |
| `RRF_WEIGHTS` | `1,1` | Only for `engine`: weights of the vector and the text rankings |

#### Matching and alerts

| Variable | Default | What it does |
|---|---|---|
| `MATCHING_ENGINE` | `indexed` | How documents are matched against subscriptions: `indexed`, or `loop` (one query per subscription, the reference) |
| `MATCHING_POLL_SECONDS` | `1` | Seconds between one look at the queue of documents and the next |
| `NOTIFICATIONS_POLL_SECONDS` | `5` | The same for the emails to send |
| `DIGEST_HOUR` | `7` | Local hour, from 0 to 23, at which digests are made: every day, and on Mondays the weekly ones. The time zone is `timezone` in the installation file |
| `EMAIL_MAX_RETRIES` | `48` | How many times an email is tried again, waiting from one minute up to an hour between them: some two days |

#### Email

| Variable | Default | What it does |
|---|---|---|
| `SMTP_HOST` | empty | Mail server. Empty: emails are marked `fallida` at once, and the inbox works the same |
| `SMTP_PORT` | `587` | |
| `SMTP_SECURITY` | `starttls` | `starttls`, `ssl` (usually port 465) or `none`, only for a server on the same machine |
| `SMTP_USER`, `SMTP_PASSWORD` | empty | If the server asks for them |
| `SMTP_FROM` | `avisos@contextcrawl.local` | Sender. Use an address of a domain that your server may send from |

#### Rate limits

The endpoints that anybody can call have a limit by address. A limit is a number and `second`, `minute`, `hour` or `day`, such as `60/minute`; `off` removes it. An address may use its whole limit at once, and then gets one more call every (period / limit). A refused call gets status 429 and a `Retry-After` header.

| Variable | Default | What it limits |
|---|---|---|
| `RATE_LIMIT_SEARCH` | `60/minute` | Searches: each one costs an embedding |
| `RATE_LIMIT_RATINGS` | `30/minute` | Ratings of results |
| `RATE_LIMIT_REGISTER` | `10/hour` | New accounts |
| `RATE_LIMIT_LOGIN` | `10/minute` | Signing in |
| `RATE_LIMIT_PUBLIC` | `120/minute` | The rest: configuration, issues, signing out, links of the emails |
| `TRUSTED_PROXIES` | `web` | Who may say, with `X-Forwarded-For`, whose request it is: addresses, networks or host names, separated by commas. The web is one, because it calls the API for its visitors |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Addresses of a reverse proxy in front of the web |

Counts are in the memory of the backend: they start again with it. In Docker Desktop every visitor may seem to come from the same address; behind a reverse proxy, set `FORWARDED_ALLOW_IPS` to its address as the web sees it. If the API itself is behind a proxy, add that proxy to `TRUSTED_PROXIES`.

### The installation file

`config/installation.yaml` says what this installation is: its name, its sources, the filters of the search and the time zone. It is mounted into the backend, which reads it once: after editing it, `docker compose restart backend`. Adding a source or a filter does not require touching the engine.

```yaml
nombre: Boletines Córdoba
timezone: America/Argentina/Cordoba    # of the digests; UTC if it is missing
seed: true                             # load the sample documents if the database is empty

fuentes:
  - clave: cordoba-provincial
    nombre: Boletín Oficial de la Provincia de Córdoba
    metadata:                          # optional: added to every document of the source
      provincia: Córdoba
    conector:                          # optional: without it, documents are added through the API
      tipo: boletin-cba-pdf-diario     # key registered in backend/src/connectors/registry.py
      frecuencia_minutos: 1440         # once a day
      config:
        url_template: "https://boletinoficial.cba.gov.ar/wp-content/4p96humuzp/{anio}/{mes}/{seccion}_Secc_{ddmmyy}.pdf"
        secciones: [1, 2, 3, 4, 5]

filtros:
  - {clave: provincia, etiqueta: Provincia, tipo: seleccion}
  - {clave: monto, etiqueta: Monto estimado, tipo: rango_numerico}
```

`metadata` holds values that are the same for the whole source, so that the filters find its documents; at startup it is also added to the ones the source already has. A declared filter that no source can fill is logged as a warning.

## Everyday operation

### Sources and the scheduler

The scheduler runs **inside the `backend` container**. When a source is due comes from its last successful run, so a restart does not put it off: an overdue source runs shortly after startup (one after another if there are several, two at once at most), and another waits for its time. Days that were missed are not fetched later ([plan 13](docs/plans/13-source-coverage-and-health.md)).

To run one without waiting:

```bash
curl -X POST -H "Authorization: Bearer $OPERATOR_TOKEN" \
  http://localhost:9101/v1/fuentes/cordoba-provincial/ejecutar
```

Each run is recorded in `ejecuciones_fuente` (start, end, discovered, new, existing, changed, errors). Its state is `completada`, `partial` if some items failed, or `fallida` if all did or the source could not be read. A document that failed is processed again the next time it arrives. A record that arrives again with other content is counted as `changed` and logged; the stored one is kept ([plan 11](docs/plans/11-deadlines-and-amendments.md)).

```bash
docker compose exec db psql -U bo_ia -d bo_ia -c \
  "SELECT f.clave, e.inicio, e.estado, e.nuevos, e.errores FROM ejecuciones_fuente e JOIN fuentes f ON f.id = e.fuente_id ORDER BY e.id DESC LIMIT 10"
```

Connectors available today (`backend/src/connectors/registry.py`):

| Key (`tipo`) | What it does |
|---|---|
| `boletin-cba-pdf-diario` | Direct HTTP (`curl`, see Etapa 5) against `boletinoficial.cba.gov.ar`: predictable PDF URL per section/date, extracts text with `pypdf` and splits it at the closing line of each notice. One `DocumentoNormalizado` per notice, with its number, pages and issue. The cover is kept but not searchable, and text without a closing line is one "unsegmented" document. |
| `comprar-gob-ar-csv` | Streams the open dataset of national tenders (`Convocatorias.csv`, datos.gob.ar) and produces one `DocumentoNormalizado` per row, filtered by `anio_desde` (Etapa 5). |
| `bop-cordoba-scrapy` | Scrapy + PDF extraction against the official gazette of the Diputación de Córdoba, **Spain** (`bop.dipucordoba.es`) — the reference connector from Etapa 2, unused by any installation since Etapa 5 (it pointed at the wrong site by mistake; see `docs/specs/etapa-5-segundo-vertical/`). It stays registered and tested, so already-proven code is not deleted. |

Notices that the gazette prints as an image have no text to extract: only their closing line is stored. `municipio` is read from the title of municipal notices. `organismo` and `monto` are not read from gazette notices yet ([plan 8](docs/plans/08-classification-and-field-extraction.md)), so filtering by them excludes those.

Each connector's tests run against local fixtures; tests marked `live` (excluded by default and from CI) run against the real site/dataset.

### Operator token

Adding a document (`POST /v1/documentos`) and running a source require the secret of `OPERATOR_TOKEN`, sent as `Authorization: Bearer <token>`. **Without it both endpoints reject every request**, with a warning at startup; the scheduler and the sample data do not need it. A user's session does not replace it. Scripts that called these endpoints before have to send it. To change it, edit `.env` and run `docker compose up -d backend`.

### Waiting work

Matching and sending emails happen in the background, and what is waiting is in the database, so a restart loses nothing:

```bash
docker compose exec db psql -U bo_ia -d bo_ia -c "SELECT count(*), max(attempts), max(last_error) FROM matching_queue"
docker compose exec db psql -U bo_ia -d bo_ia -c \
  "SELECT estado, count(*), max(error_proveedor) FROM entregas_notificacion WHERE canal = 'correo' GROUP BY estado"
```

### Backups

```bash
docker compose exec -T db pg_dump -U bo_ia -Fc bo_ia > backup.dump
docker compose exec -T db pg_restore -U bo_ia -d bo_ia --clean --if-exists < backup.dump
```

Keep `.env` too: without `LINK_SECRET`, the links of the emails that were sent stop working.

### Upgrading

```bash
docker compose exec -T db pg_dump -U bo_ia -Fc bo_ia > before-upgrade.dump
git pull
docker compose up -d --build      # the backend applies the migrations when it starts
```

Compare your `.env` with `.env.example` for new variables. What to do by hand, coming from an older version:

- **No `OPERATOR_TOKEN` in your `.env`:** set it, or nothing can be added through the API.
- **Stored gazette sections:** before the notices were split, a whole section was one document. Split the stored ones, or the next run for the same day adds its notices next to them:

  ```bash
  docker compose exec backend python -m src.commands.resegment --source cordoba-provincial --dry-run
  docker compose exec backend python -m src.commands.resegment --source cordoba-provincial --refetch
  ```

  `--refetch` downloads each PDF again to know the pages, and uses the saved text when it cannot; without it the notices have no page. Choose it on the first run: a section that has been split is not split again. It raises no alerts, keeps the matches and ratings of the replaced sections, and can be run again if it is interrupted.
- **Emails that were interrupted** before there were retries are marked `fallida`, and are not sent now.

To go back to an older version, let the two queues above empty first, and then take the migrations back with the newer code: `docker compose exec backend alembic downgrade <revision>`.

### Notices and filters of the gazette

Notices that the gazette prints as an image have no text to extract: only their closing line is stored. `municipio` is read from the title of municipal notices. `organismo` and `monto` are not read from gazette notices yet ([plan 8](docs/plans/08-classification-and-field-extraction.md)), so filtering by them excludes those.

### Search engine

`SEARCH_ENGINE` chooses who answers searches. `postgres` (the default) uses pgvector and PostgreSQL full-text search. `engine` uses an engine in the backend process: BM25, a vector index with filters applied during the search, and the same fusion. The response is the same. The engine is built from the database at every start, and PostgreSQL answers until it is ready; it takes about 5.5 GB per million fragments ([numbers](docs/plans/04-hybrid-ranking-engine.md#numbers)).

## Using it

### Accounts and subscriptions

On the web: **Crear cuenta**, **Suscripciones** to say what interests you (a text, and filters if you want), and **Avisos** for what was found. Each subscription says how to be told: in the inbox, by email or both, and whether emails come one by one, in a daily digest or in a weekly one. The inbox never waits.

The same through the API, with a session cookie:

```bash
curl -c cookies.txt -X POST http://localhost:9101/v1/auth/registro \
  -H 'content-type: application/json' -d '{"email": "cliente@example.org", "password": "a-long-password"}'
curl -b cookies.txt -c cookies.txt -X POST http://localhost:9101/v1/auth/login \
  -H 'content-type: application/json' -d '{"email": "cliente@example.org", "password": "a-long-password"}'
curl -b cookies.txt -X POST http://localhost:9101/v1/suscripciones \
  -H 'content-type: application/json' \
  -d '{"texto_busqueda": "licitaciones de obra vial", "filtros": {"municipio": "Carlos Paz"},
       "canales": ["bandeja", "correo"], "frecuencia_notificacion": "daily"}'
curl -b cookies.txt "http://localhost:9101/v1/notificaciones?canal=bandeja&unread=true"
```

`canales` is `["bandeja"]` by default. `frecuencia_notificacion` is `immediate` (the default), `daily` or `weekly`. Sessions are rows of the `sesiones` table, with an HttpOnly cookie.

### How an alert is made

When a new document has been ingested it is left in a queue, in the same transaction. A background thread finds the subscriptions whose filters it passes and whose text is close enough to one of its fragments, from an index in memory that is kept current from the database ([numbers](docs/plans/03-subscription-matching-engine.md#numbers)). The match and its deliveries are written together; the inbox entry is one of them.

Another thread sends the emails. One that fails is tried again, unless the failure is permanent (an address that does not exist). If the backend dies between the moment the server accepts an email and the moment that is recorded, the email is sent again, with the same `Message-ID`: there is no way to send exactly once. A digest is one email per user and period with everything that is new; a match is in exactly one.

An alert shows the excerpt that matched with the words it shares with the subscription, or says that it matched by meaning if there are none, together with the notice number, the pages, the date, the score and the filters. Every email has a link to pause the subscription without signing in (see `LINK_SECRET`).

### API

Interactive documentation is at `http://localhost:9101/docs`. *Public* endpoints have a [rate limit](#rate-limits).

| Method and path | Who | What it does |
|---|---|---|
| `GET /v1/search` | public | Search (`q`, `date_from`, `date_to`, `limit`, `mode`, `filtro.<key>` for each declared filter) |
| `GET /v1/issues/{source}/{issue}` | public | The documents of one issue, together (for example `cordoba-provincial/4_Secc_240926`) |
| `GET /v1/config` | public | Installation name and declared filters |
| `POST /v1/valoraciones` | public | Records a thumbs up/down on a result |
| `POST /v1/auth/registro` | public | Creates an account (email and password) |
| `POST /v1/auth/login` | public | Signs in, sets the `contextcrawl_sesion` cookie |
| `POST /v1/auth/logout` | public | Ends the current session |
| `GET /v1/pause-links` | a signed link | What the link of an email would pause |
| `POST /v1/pause-links` | a signed link | Pauses it |
| `POST /v1/suscripciones` | a user | Creates a subscription |
| `GET /v1/suscripciones` | a user | Lists your subscriptions |
| `PATCH /v1/suscripciones/{id}` | a user | Changes its channels or frequency |
| `POST /v1/suscripciones/{id}/pausar` | a user | Pauses it |
| `POST /v1/suscripciones/{id}/reanudar` | a user | Resumes it |
| `DELETE /v1/suscripciones/{id}` | a user | Deletes it |
| `GET /v1/notificaciones` | a user | Your alerts, explained (`canal`, `unread`, `limit`, `before`) |
| `GET /v1/notificaciones/unread-count` | a user | How many are unread |
| `POST /v1/notificaciones/{id}/read` | a user | Marks one as read |
| `POST /v1/notificaciones/read` | a user | Marks all as read |
| `POST /v1/documentos` | the operator | Ingests a document (validates, chunks, generates embeddings) |
| `POST /v1/fuentes/{clave}/ejecutar` | the operator | Runs the connector of a source now |
| `GET /health` | anybody | Health check |

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

## Development

### Without Docker

You need Python 3.12 and PostgreSQL 16 with [pgvector](https://github.com/pgvector/pgvector). The easiest database is the one of Docker: `docker compose up -d db`.

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# The variables of .env are for Docker, where the database is "db". Here it is localhost:
export DATABASE_URL="postgresql+psycopg://bo_ia:dev_only_change_me@localhost:9100/bo_ia"
export INSTALLATION_CONFIG="$PWD/../config/installation.yaml"
export OPERATOR_TOKEN="$(openssl rand -hex 32)"
export EMBEDDING_PROVIDER=hashed SIMILARITY_THRESHOLD=0.25      # leave out to use the real model

.venv/bin/alembic upgrade head
.venv/bin/uvicorn src.api.main:app --port 9101 --reload
```

With the real model, the first start downloads it to the Hugging Face cache; `EMBEDDING_CACHE_DIR` chooses another place. In another terminal, the web:

```bash
cd web
../backend/.venv/bin/pip install "uvicorn[standard]" jinja2 python-multipart httpx
BACKEND_INTERNAL_URL=http://localhost:9101 ../backend/.venv/bin/uvicorn app:app --port 9102 --reload
```

To see the emails without a mail server, run one that prints them (`pip install aiosmtpd`) and point the backend to it:

```bash
python -m aiosmtpd -n -l localhost:1025
export SMTP_HOST=localhost SMTP_PORT=1025 SMTP_SECURITY=none PUBLIC_WEB_URL=http://localhost:9102 LINK_SECRET=development
```

### Without the model

`EMBEDDING_PROVIDER=hashed` replaces the real model with offline vectors: no download, no network, and texts are close if they share words. `EMBEDDING_PROVIDER=precomputed` replays vectors from a file (`EMBEDDING_PRECOMPUTED`). Both need a lower `SIMILARITY_THRESHOLD` than the real model, and a database of their own: the vectors of two providers cannot be compared.

### Running the tests

From `backend/`, with the environment above and the database running. The tests use databases of their own, `bo_ia_test` and `bo_ia_test_migrations`, which they create and drop: do not run two sessions at once.

```bash
.venv/bin/pytest -m "not slow and not docker and not live"   # the fast suite: no network, no model
.venv/bin/pytest tests/api/test_search.py                    # one file
.venv/bin/pytest -m slow                                     # downloads and uses the real model (about 1 GB)
.venv/bin/pytest -m docker                                   # brings everything up with docker compose, and stops it
.venv/bin/pytest -m live                                     # against the real sites
.venv/bin/ruff check src tests ../web                        # lint
```

CI (`.github/workflows/ci.yml`) runs everything but `docker` and `live` in one job, and a smoke test of the stack in another, on every push and pull request to `main`.

### Benchmark

`python -m src.benchmark`, from `backend/`, generates a corpus with known answers and measures search and matching against it, with no database, network or model. See [how to run it](docs/plans/README.md#automated-checks) and the [first numbers](docs/plans/01-synthetic-corpus-and-benchmark.md#first-numbers).

```bash
.venv/bin/python -m src.benchmark run --documents 2000 --out benchmark-output/run
```

## Troubleshooting

| What happens | Why, and what to do |
|---|---|
| `401` from `POST /v1/documentos` or `.../ejecutar` | `OPERATOR_TOKEN` is not set, is not the one that was sent, or the container was not created again after editing `.env`: `docker compose up -d backend` |
| A change in `.env` has no effect | `docker compose restart` does not read it. Use `docker compose up -d` |
| The backend stops at startup | The last line of `docker compose logs backend` names the variable or the line of the installation file that is not valid |
| `password authentication failed` | `POSTGRES_PASSWORD` changed after the database was created. Put the old one back, or change it inside PostgreSQL too |
| A search finds nothing | `SIMILARITY_THRESHOLD` is too high for the embedding provider, or the provider changed on a database that had documents. `mode=all` has no threshold |
| `429 Too Many Requests` | A [rate limit](#rate-limits). If every visitor shares it, the proxy in front is not trusted: see `FORWARDED_ALLOW_IPS` and `TRUSTED_PROXIES` |
| No emails | `SELECT estado, error_proveedor FROM entregas_notificacion WHERE canal = 'correo' ORDER BY id DESC LIMIT 5`. `pendiente` with an error: it will be tried again. `fallida`: permanent, or `SMTP_HOST` is empty. No rows: the subscription does not have the channel `correo`. With `daily` or `weekly` they wait for `DIGEST_HOUR` |
| Emails without the link to pause | Set `LINK_SECRET` and `PUBLIC_WEB_URL` |
| A form of the web answers "Solicitud rechazada" | The address in the browser is not the one the web receives. Behind a proxy, set `PUBLIC_WEB_URL` |
| A source does not run | It is not due (see `ejecuciones_fuente`), or its last run is `fallida` and it waits for the next one. Run it by hand |

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

## Repository structure

- `backend/` — Ingestor, Processor and API (Python/FastAPI), consolidated into a single service. See `backend/src/` (code) and `backend/tests/` (tests).
- `web/` — search UI (Jinja2 + htmx).
- `config/` — one installation file per thematic installation.
- `docs/` — documentation: `plans/` (upcoming features), `specs/` (spec-kit artifacts for the SDD phase workflow), `design/` (design specs) and `reports/` (research reports and proofs of concept).

## License

Released under the [MIT License](LICENSE).
