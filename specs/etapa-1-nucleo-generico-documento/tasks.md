# Tasks: Etapa 1 — Núcleo genérico (Documento)

Framework: spec-kit (track default)
Feature ID: f_01m37e47q8s40qfzv53n5bpa1y
Fuente: `plan.md` de esta feature (Project Structure y Research)

Orden: toda dependencia aparece antes que la tarea que depende de ella. `[P]` marca tareas que pueden hacerse en paralelo (no dependen entre sí y tocan archivos distintos).

## Tasks

### Setup

- [ ] T001 Agregar `PyYAML` como dependencia (parsear `installation.yaml`) en `backend/pyproject.toml`
- [ ] T002 [P] Documentar `INSTALLATION_CONFIG` en `.env.example`
- [ ] T003 Montar `installation.yaml` en el contenedor `backend` y setear `INSTALLATION_CONFIG` en `docker-compose.yml`, depends on T002

### Modelo de datos y migración

- [ ] T004 Escribir el contrato `DocumentoNormalizado` (dataclass, sin dependencias de SQLAlchemy) en `backend/src/ingestor/contract.py` (FR-002)
- [ ] T005 En `backend/src/db/models.py`: renombrar `Boletin`→`Documento` (tabla `documentos`) y `Fragmento.boletin_id`→`documento_id`; agregar el modelo `Fuente` (tabla `fuentes`: `clave`, `nombre`, `config` JSONB); agregar a `Documento` las columnas `fuente_id`, `metadata` (JSONB), `estado`, `version_ingesta`, con índice GIN sobre `metadata` (FR-001, FR-004, FR-005), depends on T004
- [ ] T006 Escribir la migración Alembic única que aplica el cambio de T005 sobre el esquema existente: crea `fuentes` con backfill desde `jurisdiccion`, renombra `boletines`→`documentos` (columnas, constraints, índices) y `fragmentos.boletin_id`→`documento_id`, agrega `metadata`/`estado`/`version_ingesta`/índice GIN, con `downgrade` completo, en `backend/src/db/migrations/versions/` (FR-014, FR-015), depends on T005
- [ ] T007 Escribir el test del ciclo `upgrade → downgrade → upgrade` de la migración de T006 sobre datos de ejemplo previos, verificando el backfill, en `backend/tests/test_migrations.py` (SC-006), depends on T006
- [ ] T008 Actualizar `backend/tests/conftest.py` (nombre de tabla en el `TRUNCATE`) para el esquema renombrado, depends on T006

### Tests primero (TDD)

- [ ] T009 [P] Escribir tests que fallen para `ingerir_documento` (idempotencia por `fuente_id`+`identificador_externo` y por hash, conservación del original ante fallo de procesamiento) en `backend/tests/ingestor/test_ingestor.py` (FR-002, FR-003, FR-006), depends on T006
- [ ] T010 [P] Escribir tests que fallen para `aplicar_filtros` (selección, rango numérico, clave no declarada) en `backend/tests/search/test_filters.py` (FR-009, FR-012, FR-013), depends on T004
- [ ] T011 [P] Escribir tests que fallen para la carga y validación de `installation.yaml` (archivo inválido no debe arrancar el servicio, upsert idempotente de fuentes) en `backend/tests/config/test_installation.py` (FR-007, FR-008), depends on T006
- [ ] T012 [P] Escribir tests que fallen para `GET /v1/config` (expone los filtros declarados con su etiqueta) en `backend/tests/api/test_config.py` (FR-010), depends on T011
- [ ] T013 [P] Escribir un test de punta a punta que falle: dos fuentes conviven en la misma instalación y filtrar por `municipio=Carlos Paz` excluye `Noetinger`, en `backend/tests/api/test_search_filters.py` (FR-011, SC-002, SC-005), depends on T010

### Implementación

- [ ] T014 Implementar `ingerir_documento(session, doc)` en `backend/src/ingestor/contract.py`, reemplazando la lógica de fragmentar/embeber duplicada entre `ingest.py` y `seed.py`, depends on T009
- [ ] T015 [P] Implementar el adaptador del Boletín en `backend/src/ingestor/adapters/boletin.py` (traduce sus campos a `DocumentoNormalizado`, completa `provincia`/`municipio`/`organismo` en `metadata`), depends on T014
- [ ] T016 Implementar el loader y el modelo pydantic de `installation.yaml` en `backend/src/config/installation.py`, depends on T011
- [ ] T017 Implementar `aplicar_filtros(consulta, filtros, config)` en `backend/src/search/filters.py`, depends on T010
- [ ] T018 Reescribir el endpoint de ingesta sobre `ingerir_documento` y el adaptador del Boletín (`POST /v1/documentos`, reemplaza `POST /v1/boletines`) en `backend/src/api/ingest.py`, depends on T015
- [ ] T019 Agregar `filtro.<clave>` a `GET /v1/search` vía `aplicar_filtros` y actualizar los nombres de la respuesta (`documento_id`, `identificador_externo`, `url_fuente`) en `backend/src/api/search.py`, depends on T017
- [ ] T020 Implementar `GET /v1/config` exponiendo los filtros declarados en `backend/src/api/config.py`, depends on T016, depends on T012
- [ ] T021 Cargar `installation.yaml` al arrancar y hacer upsert idempotente de `fuentes` en el `lifespan` de `backend/src/api/main.py`, depends on T016
- [ ] T022 Adaptar `backend/src/seed/seed.py` para usar `ingerir_documento` y el adaptador del Boletín, y crear `backend/src/seed/sample_documentos.json` con documentos de al menos dos municipios, reemplazando `backend/src/seed/sample_boletines.json`, depends on T018

### Interfaz web

- [ ] T023 Generar los controles de filtro en `web/templates/search.html` a partir de `GET /v1/config`, ajustando `web/app.py`, depends on T020
- [ ] T024 Actualizar `web/templates/_resultados.html` a los nuevos nombres de campo (`identificador_externo`, `url_fuente`), depends on T019

### Pulido y verificación

- [ ] T025 Confirmar la versión de pgvector instalada en `pgvector/pgvector:pg16` y correr una prueba de recall con un filtro selectivo sobre el índice HNSW (riesgo 10.6 del design spec), depends on T019
- [ ] T026 [P] Crear `installation.yaml` en la raíz del repo para el vertical Boletín, con los filtros `provincia` y `municipio` declarados, depends on T016
- [ ] T027 Actualizar `README.md` (endpoints renombrados, ejemplo de `installation.yaml`), depends on T018, depends on T020
- [ ] T028 Correr la suite completa (migración, filtros, config, ingesta, búsqueda, feedback, smoke Docker) y confirmar cada escenario de aceptación y criterio de éxito de `spec.md`; registrar los resultados como evidencia para la fase `verify`, depends on T007, depends on T008, depends on T013, depends on T021, depends on T022, depends on T023, depends on T024, depends on T025, depends on T026, depends on T027
