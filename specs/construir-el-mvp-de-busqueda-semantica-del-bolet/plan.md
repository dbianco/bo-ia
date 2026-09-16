# Plan: MVP público de búsqueda semántica del Boletín Oficial

Framework: spec-kit (track default)
Feature ID: f_01m2npz2d7t6489bgwchqas3wm
Fuente: `spec.md` de esta feature y `docs/superpowers/specs/2026-09-16-boletin-oficial-design.md` (v0.4)

## Technical Context

- **Lenguaje y versión:** Python 3.12 para el backend (Ingestor + Procesador + API consolidados, ver sección 6 del design spec).
- **Dependencias principales:** FastAPI (API), SQLAlchemy + psycopg (acceso a Postgres), el cliente Python de pgvector, `sentence-transformers` (sirve `Qwen/Qwen3-Embedding-0.6B` localmente), Alembic (migraciones), Jinja2 + htmx (interfaz web server-rendered).
- **Almacenamiento:** PostgreSQL 16 con la extensión pgvector (`pgvector/pgvector:pg16`), según secciones 6 y 7 del design spec.
- **Herramientas de testing:** pytest para tests unitarios e de integración del backend; un smoke test que levanta `docker compose up` y ejercita el endpoint de búsqueda de punta a punta, para validar FR-016 y SC-006.
- **Plataforma objetivo:** contenedores Docker en macOS y Windows vía Docker Desktop, CPU-only (sin dependencia de GPU), para desarrollo local (sección 15 del design spec).
- **Objetivos de performance y restricciones:** tiempo de respuesta de búsqueda menor a 2 segundos (SC-004) sobre el corpus inicial; el modelo de embeddings debe correr en CPU dentro de ese presupuesto para la cantidad de fragmentos esperada en el MVP.

## Constitution Check

- **Sin datos personales en logs:** los boletines son registros públicos oficiales; el MVP no tiene autenticación, así que los únicos datos de usuario que se registran son el texto de la consulta y el valor de la valoración (pulgar arriba/abajo), sin identificadores personales.
- **Timeout y retry explícitos en llamadas HTTP salientes:** la única llamada saliente del MVP es la descarga del modelo de embeddings en el primer arranque (vía `huggingface_hub`); se configura con timeout y reintentos explícitos en vez de depender de los valores por defecto de la librería.
- **Migraciones de esquema reversibles con rollback probado:** el esquema (`boletines`, `fragmentos`, `tags`, `fragmento_tags`, `valoraciones`) se gestiona con Alembic, con una migración `down` probada por cada `up`, desde el primer commit del esquema.
- **Cambios de API pública aditivos dentro de una versión mayor:** la API interna arranca versionada bajo `/v1/...` desde el día uno, aunque todavía no tiene consumidores externos, para no tener que introducir versionado más tarde cuando llegue el cliente MCP de la Etapa 4.
- **Secretos desde el entorno, nunca desde el código:** credenciales de Postgres y cualquier credencial futura del feed de ingesta viven en `.env` (ignorado por git), con `.env.example` documentando las claves requeridas, tal como ya define la sección 15 del design spec.
- **Tests en CI antes de mergear, build roja bloquea el merge:** `.github/workflows/ci.yml` corre lint (ruff) y la suite de pytest en cada push/PR a `main`, más un smoke test de Docker en un job aparte; verificado con corridas reales en GitHub Actions.
- **Accesibilidad, controles alcanzables por teclado y etiquetados:** el formulario de búsqueda, los filtros de fecha y los íconos de pulgar arriba/abajo se implementan con controles HTML semánticos nativos (`<button>`, `<input>`, `<label>`), operables por teclado por defecto, verificado manualmente antes de dar por cerrado el MVP.

## Project Structure

Lista final real y completa (actualizada tras `implement` y el follow-on de búsqueda híbrida; ver `verify-evidence.md` para el detalle de qué se verificó de cada pieza). Un archivo por línea, para que el chequeo `scope_drift` matchee exacto:

- `.dockerignore`
- `.env.example`
- `.gitignore`
- `README.md`
- `docker-compose.yml`
- `.github/workflows/ci.yml`
- `docs/superpowers/specs/2026-09-16-boletin-oficial-design.md`
- `backend/Dockerfile`
- `backend/alembic.ini`
- `backend/entrypoint.sh`
- `backend/pyproject.toml`
- `backend/src/__init__.py`
- `backend/src/api/__init__.py`
- `backend/src/api/deps.py`
- `backend/src/api/feedback.py`
- `backend/src/api/ingest.py`
- `backend/src/api/main.py`
- `backend/src/api/search.py`
- `backend/src/db/__init__.py`
- `backend/src/db/migrations/README`
- `backend/src/db/migrations/env.py`
- `backend/src/db/migrations/script.py.mako`
- `backend/src/db/migrations/versions/113ce16dc179_enable_pgvector_and_create_boletines.py`
- `backend/src/db/migrations/versions/20e22678f33f_create_tags_and_fragmento_tags.py`
- `backend/src/db/migrations/versions/7b248b8b4274_create_valoraciones.py`
- `backend/src/db/migrations/versions/9aaa3783a1df_add_fragmentos_texto_tsv_fulltext_search.py`
- `backend/src/db/migrations/versions/fa9cc1623dda_create_fragmentos.py`
- `backend/src/db/models.py`
- `backend/src/ingestor/__init__.py`
- `backend/src/ingestor/fragmenter.py`
- `backend/src/ingestor/ingest.py`
- `backend/src/processor/__init__.py`
- `backend/src/processor/embeddings.py`
- `backend/src/processor/hybrid.py`
- `backend/src/processor/threshold.py`
- `backend/src/seed/sample_boletines.json`
- `backend/src/seed/seed.py`
- `backend/tests/__init__.py`
- `backend/tests/api/test_feedback.py`
- `backend/tests/api/test_ingest.py`
- `backend/tests/api/test_search.py`
- `backend/tests/api/test_search_hybrid.py`
- `backend/tests/conftest.py`
- `backend/tests/ingestor/test_fragmenter.py`
- `backend/tests/ingestor/test_ingestor.py`
- `backend/tests/manual/accessibility-checklist.md`
- `backend/tests/processor/test_embeddings.py`
- `backend/tests/processor/test_hybrid.py`
- `backend/tests/smoke/test_docker_up.py`
- `backend/tests/test_migrations.py`
- `web/Dockerfile`
- `web/app.py`
- `web/static/htmx.min.js`
- `web/static/style.css`
- `web/templates/_gracias.html`
- `web/templates/_resultados.html`
- `web/templates/search.html`
- `specs/construir-el-mvp-de-busqueda-semantica-del-bolet/spec.md`
- `specs/construir-el-mvp-de-busqueda-semantica-del-bolet/plan.md`
- `specs/construir-el-mvp-de-busqueda-semantica-del-bolet/tasks.md`
- `specs/construir-el-mvp-de-busqueda-semantica-del-bolet/verify-evidence.md`

## Research

- **Framework de API — FastAPI:** elegido sobre Flask o Django por validación de esquemas integrada con Pydantic (encaja con FR-001, validar campos obligatorios en la ingesta) y tipado nativo, sin el peso de un framework full-stack que el MVP no necesita.
- **Interfaz web — Jinja2 + htmx (server-rendered):** en vez de una SPA separada (React/Vue). Evita un segundo toolchain de build de frontend y mantiene la arquitectura de 3 contenedores ya decidida (sección 15 del design spec); alcanza para el alcance del MVP (formulario, lista de resultados, íconos de valoración).
- **Migraciones — Alembic:** en vez de scripts SQL sueltos, para cumplir la constante de la compañía de migraciones reversibles con rollback probado.
- **Modelo de embeddings — `Qwen/Qwen3-Embedding-0.6B` self-hosted vía `sentence-transformers`:** decisión ya tomada durante la fase `specify` (spike de brainstorming), documentada en la sección 6 del design spec; no se reabre acá.
- **Umbral de similitud interno:** decisión ya tomada (FR-015); se implementa como variable de configuración del servicio `backend`, no como parámetro de la API pública.
- **Orquestación local — docker-compose de 3 servicios (`db`, `backend`, `web`):** decisión ya tomada (sección 15 del design spec); el backend cachea el modelo de embeddings en un volumen nombrado en vez de incluirlo en la imagen.
