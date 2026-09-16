# bo-ia

Plataforma de búsqueda semántica del Boletín Oficial de la Provincia de Córdoba.

## Documentación

- **Spec de diseño:** [docs/superpowers/specs/2026-09-16-boletin-oficial-design.md](docs/superpowers/specs/2026-09-16-boletin-oficial-design.md) — contexto, alcance por etapas, arquitectura y modelo de datos.
- **Feature MVP (spec-kit / SDD):** [specs/construir-el-mvp-de-busqueda-semantica-del-bolet/](specs/construir-el-mvp-de-busqueda-semantica-del-bolet/) — `spec.md`, `plan.md` y `tasks.md` de la Etapa 1.

## Estado actual

El MVP (Etapa 1) está completo según `tasks.md`: ingesta, búsqueda semántica con filtro de fechas, umbral de similitud, valoraciones (pulgar arriba/abajo) y datos de ejemplo precargados, todo corriendo en Docker con un solo comando.

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
