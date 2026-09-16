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

Árbol final real (actualizado tras la fase `implement` y el follow-on de búsqueda híbrida; ver `verify-evidence.md` para el detalle de qué se verificó de cada pieza):

```
bo-ia/
├── `docker-compose.yml`
├── `.env.example`
├── `.dockerignore`
├── `.github/workflows/ci.yml`         # lint + tests + smoke test de Docker
├── `backend/`
│   ├── `Dockerfile`
│   ├── `entrypoint.sh`                # alembic upgrade head antes de uvicorn
│   ├── `pyproject.toml`               # deps + config de ruff y pytest
│   ├── `alembic.ini`
│   ├── `src/`
│   │   ├── `ingestor/`
│   │   │   ├── `ingest.py`            # FR-001–003, FR-006: validación, hash, idempotencia
│   │   │   └── `fragmenter.py`        # FR-004–005, FR-007: fragmentación con solapamiento
│   │   ├── `processor/`
│   │   │   ├── `embeddings.py`        # Qwen3-Embedding-0.6B (real) + fake (tests)
│   │   │   ├── `threshold.py`         # FR-015: umbral de similitud
│   │   │   └── `hybrid.py`            # FR-028–029: fusión RRF (texto + vector)
│   │   ├── `api/`
│   │   │   ├── `main.py`, `deps.py`
│   │   │   ├── `search.py`            # FR-008–013, FR-015, FR-026–031: modos SEMANTIC/HYBRID/ALL
│   │   │   ├── `ingest.py`            # POST /v1/boletines
│   │   │   └── `feedback.py`          # FR-014: POST /v1/valoraciones
│   │   ├── `db/`
│   │   │   ├── `models.py`            # boletines, fragmentos (+ texto_tsv), tags, fragmento_tags, valoraciones
│   │   │   └── `migrations/`          # Alembic, 5 revisiones
│   │   └── `seed/`
│   │       ├── `sample_boletines.json`  # FR-017
│   │       └── `seed.py`
│   └── `tests/`                       # unit, api, smoke, manual (accesibilidad)
├── `web/`
│   ├── `Dockerfile`, `app.py`
│   ├── `templates/`                   # search.html, _resultados.html, _gracias.html
│   └── `static/`                      # htmx.min.js (vendorizado), style.css
├── `specs/construir-el-mvp-de-busqueda-semantica-del-bolet/`
│   ├── `spec.md`, `plan.md`, `tasks.md`
│   └── `verify-evidence.md`
└── `docs/superpowers/specs/2026-09-16-boletin-oficial-design.md`  # design spec de referencia (v0.6)
```

## Research

- **Framework de API — FastAPI:** elegido sobre Flask o Django por validación de esquemas integrada con Pydantic (encaja con FR-001, validar campos obligatorios en la ingesta) y tipado nativo, sin el peso de un framework full-stack que el MVP no necesita.
- **Interfaz web — Jinja2 + htmx (server-rendered):** en vez de una SPA separada (React/Vue). Evita un segundo toolchain de build de frontend y mantiene la arquitectura de 3 contenedores ya decidida (sección 15 del design spec); alcanza para el alcance del MVP (formulario, lista de resultados, íconos de valoración).
- **Migraciones — Alembic:** en vez de scripts SQL sueltos, para cumplir la constante de la compañía de migraciones reversibles con rollback probado.
- **Modelo de embeddings — `Qwen/Qwen3-Embedding-0.6B` self-hosted vía `sentence-transformers`:** decisión ya tomada durante la fase `specify` (spike de brainstorming), documentada en la sección 6 del design spec; no se reabre acá.
- **Umbral de similitud interno:** decisión ya tomada (FR-015); se implementa como variable de configuración del servicio `backend`, no como parámetro de la API pública.
- **Orquestación local — docker-compose de 3 servicios (`db`, `backend`, `web`):** decisión ya tomada (sección 15 del design spec); el backend cachea el modelo de embeddings en un volumen nombrado en vez de incluirlo en la imagen.
