# bo-ia

[![CI](https://github.com/dbianco/bo-ia/actions/workflows/ci.yml/badge.svg)](https://github.com/dbianco/bo-ia/actions/workflows/ci.yml)

Plataforma de búsqueda semántica del Boletín Oficial de la Provincia de Córdoba.

## Documentación

- **Spec de diseño:** [docs/superpowers/specs/2026-09-16-boletin-oficial-design.md](docs/superpowers/specs/2026-09-16-boletin-oficial-design.md) — contexto, alcance por etapas, arquitectura y modelo de datos.
- **Feature MVP (spec-kit / SDD):** [specs/construir-el-mvp-de-busqueda-semantica-del-bolet/](specs/construir-el-mvp-de-busqueda-semantica-del-bolet/) — `spec.md`, `plan.md`, `tasks.md` y `verify-evidence.md` de la Etapa 1.
- **Checklist de accesibilidad:** [backend/tests/manual/accessibility-checklist.md](backend/tests/manual/accessibility-checklist.md) (WCAG 2.1 AA).

## Estado actual

El MVP (Etapa 1) está completo: las 31 tareas de `tasks.md` implementadas y verificadas con comandos reales (tests, `docker compose` real, CI real en GitHub Actions). La feature está en la fase `verify` del flujo de SDD (spec-kit); ver `verify-evidence.md` para el detalle de qué se verificó y los gaps conocidos (Windows sin probar, tiempo de respuesta sin medición automatizada, evaluación manual pendiente de datos reales).

Endpoints disponibles en el backend (`http://localhost:9101`):

| Método y ruta | Qué hace |
|---|---|
| `GET /v1/search` | Búsqueda semántica (`q`, `date_from`, `date_to`, `limit`) |
| `POST /v1/boletines` | Ingesta de un boletín (valida, fragmenta, genera embeddings) |
| `POST /v1/valoraciones` | Registra un pulgar arriba/abajo sobre un resultado |
| `GET /health` | Chequeo de salud |

## Estructura del repositorio

- `backend/` — Ingestor, Procesador y API (Python/FastAPI), consolidados en un solo servicio. Ver `backend/src/` (código) y `backend/tests/` (tests).
- `web/` — interfaz de búsqueda (Jinja2 + htmx).
- `specs/` — artefactos del framework spec-kit (spec, plan, tareas) para el flujo de fases del SDD.
- `docs/` — spec de diseño original y documentación de referencia.

## Cómo correr esto localmente

Requiere Docker y Docker Compose (Docker Desktop en macOS o Windows).

```bash
cp .env.example .env
docker compose up --build
```

Esto levanta tres servicios: `db` (PostgreSQL + pgvector, puerto 9100), `backend` (Ingestor + Procesador + API, puerto 9101) y `web` (interfaz de búsqueda, puerto 9102). Los puertos están en el rango 9100 para evitar choques con otras apps corriendo en la máquina.

Al arrancar, el backend corre las migraciones de Alembic automáticamente y carga un puñado de boletines de ejemplo si la base está vacía. La primera vez descarga el modelo de embeddings (`Qwen/Qwen3-Embedding-0.6B`, ~1 GB) y lo cachea en un volumen; los arranques siguientes son instantáneos.

Abrí `http://localhost:9102` para usar la interfaz, o probá la API directamente:

```bash
curl http://localhost:9101/health
curl "http://localhost:9101/v1/search?q=presupuesto+provincial"
```

## Cómo correr los tests

Con Python 3.12 y el servicio `db` levantado (`docker compose up -d db`):

```bash
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export DATABASE_URL="postgresql+psycopg://bo_ia:dev_only_change_me@localhost:9100/bo_ia"

.venv/bin/pytest -m "not slow and not docker"   # rápidos, con embeddings fake
.venv/bin/pytest -m slow                        # descarga y usa el modelo real (~1 GB)
.venv/bin/pytest -m docker                      # smoke test: levanta todo con docker compose
```

El workflow de CI (`.github/workflows/ci.yml`) corre los dos primeros grupos en un job y el smoke test en otro, en cada push y pull request a `main`.
