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
- **Tests en CI antes de mergear, build roja bloquea el merge:** la suite de pytest queda documentada como chequeo obligatorio; falta el workflow de CI en sí, que queda anotado como tarea pendiente para la fase `tasks`.
- **Accesibilidad, controles alcanzables por teclado y etiquetados:** el formulario de búsqueda, los filtros de fecha y los íconos de pulgar arriba/abajo se implementan con controles HTML semánticos nativos (`<button>`, `<input>`, `<label>`), operables por teclado por defecto, verificado manualmente antes de dar por cerrado el MVP.

## Project Structure

```
bo-ia/
├── `docker-compose.yml`
├── `.env.example`
├── `backend/`
│   ├── `Dockerfile`
│   ├── `pyproject.toml`
│   ├── `src/`
│   │   ├── `ingestor/`            # FR-001–007: validación, hash, fragmentación
│   │   ├── `processor/`           # embeddings (Qwen3-Embedding-0.6B), hook de tagging futuro
│   │   ├── `api/`                 # FastAPI: endpoints de búsqueda, ingesta y valoraciones
│   │   ├── `db/`
│   │   │   ├── `models.py`        # boletines, fragmentos, tags, fragmento_tags, valoraciones
│   │   │   └── `migrations/`      # Alembic
│   │   └── `seed/`
│   │       └── `sample_boletines.json`  # FR-017
│   └── `tests/`
├── `web/`
│   ├── `Dockerfile`
│   ├── `templates/`               # Jinja2: búsqueda, resultados, pulgares
│   └── `static/`
├── `specs/construir-el-mvp-de-busqueda-semantica-del-bolet/`
│   ├── `spec.md`
│   └── `plan.md`
└── `docs/superpowers/specs/2026-09-16-boletin-oficial-design.md`  # design spec de referencia
```

## Research

- **Framework de API — FastAPI:** elegido sobre Flask o Django por validación de esquemas integrada con Pydantic (encaja con FR-001, validar campos obligatorios en la ingesta) y tipado nativo, sin el peso de un framework full-stack que el MVP no necesita.
- **Interfaz web — Jinja2 + htmx (server-rendered):** en vez de una SPA separada (React/Vue). Evita un segundo toolchain de build de frontend y mantiene la arquitectura de 3 contenedores ya decidida (sección 15 del design spec); alcanza para el alcance del MVP (formulario, lista de resultados, íconos de valoración).
- **Migraciones — Alembic:** en vez de scripts SQL sueltos, para cumplir la constante de la compañía de migraciones reversibles con rollback probado.
- **Modelo de embeddings — `Qwen/Qwen3-Embedding-0.6B` self-hosted vía `sentence-transformers`:** decisión ya tomada durante la fase `specify` (spike de brainstorming), documentada en la sección 6 del design spec; no se reabre acá.
- **Umbral de similitud interno:** decisión ya tomada (FR-015); se implementa como variable de configuración del servicio `backend`, no como parámetro de la API pública.
- **Orquestación local — docker-compose de 3 servicios (`db`, `backend`, `web`):** decisión ya tomada (sección 15 del design spec); el backend cachea el modelo de embeddings en un volumen nombrado en vez de incluirlo en la imagen.
