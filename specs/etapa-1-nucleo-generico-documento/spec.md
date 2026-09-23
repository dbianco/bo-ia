# Feature: Etapa 1 — Núcleo genérico (Documento)

Framework: spec-kit (track default)
Feature ID: f_01m37e47q8s40qfzv53n5bpa1y
Fuente: `docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md` (v0.2), sección 8 "Diseño detallado de la Etapa 1"

## User Scenarios

### Primary user story

Como desarrollador de la plataforma, quiero que el núcleo de ingesta y búsqueda sea genérico (`Documento`, no `Boletin`) y configurable por instalación, para poder incorporar una segunda fuente temática sin duplicar el motor.

### Acceptance scenarios

1. **Given** el núcleo del código (modelos, ingesta, API de búsqueda), **When** se busca la cadena `Boletin` (grep, sin distinguir mayúsculas), **Then** no aparece, salvo en el adaptador del Boletín, el seed y la configuración de instalación.
2. **Given** una instalación con dos fuentes configuradas en `installation.yaml`, **When** se ingieren documentos con el mismo `identificador_externo` en cada una, **Then** ambos documentos se persisten sin colisión y son consultables juntos o filtrados por fuente.
3. **Given** un `installation.yaml` con los filtros `provincia` y `municipio` declarados, **When** se llama a `GET /v1/config`, **Then** la respuesta expone esos dos filtros con su etiqueta, sin cambios de código.
4. **Given** documentos con `metadata.municipio` "Carlos Paz" y "Noetinger", **When** se busca con `filtro.municipio=Carlos Paz`, **Then** solo aparecen resultados de Carlos Paz.
5. **Given** una clave de filtro no declarada en `installation.yaml`, **When** se envía como parámetro de búsqueda, **Then** la API responde 422 sin ejecutar la consulta.
6. **Given** la suite de pruebas del MVP (ingesta idempotente, filtros de fecha, búsqueda híbrida, feedback, smoke Docker), **When** se ejecuta después de la migración y el renombre, **Then** sigue pasando en verde.
7. **Given** la migración Alembic de esta etapa aplicada sobre una base con datos de ejemplo, **When** se revierte (`downgrade`) y se vuelve a aplicar (`upgrade`), **Then** el esquema y los datos quedan consistentes, sin pérdida irreversible.

## Functional Requirements

### Núcleo de documentos

- **FR-001**: The system MUST store documents in a source-agnostic `documentos` table (`fuente_id`, `identificador_externo`, `fecha`, `titulo`, `texto`, `url_fuente`, `hash_contenido`, `estado`, `metadata`, `version_ingesta`), replacing `boletines`.
- **FR-002**: The system MUST expose a single ingestion function `ingerir_documento(session, doc)` implementing idempotency by `(fuente_id, identificador_externo)` or `hash_contenido`, used by both `POST /v1/documentos` and the seed loader (replacing the duplicated logic in `ingest.py` and `seed.py`).
- **FR-003**: WHEN a later processing stage fails (fragmentation, embedding), the system SHALL retain the original document text and mark `estado = "fallido"` rather than deleting the record.
- **FR-004**: Each `fragmento` MUST reference `documento_id` and retain a denormalized `fecha`, so date filters do not require a join.

### Fuentes

- **FR-005**: The system MUST store sources in a `fuentes` table (`clave`, `nombre`, `config` JSONB) and reference them from `documentos.fuente_id`, replacing the free-text `jurisdiccion` column.
- **FR-006**: The system MUST allow more than one `fuente` to coexist within a single instalación without identifier collisions across sources (FR-002's idempotency key includes `fuente_id`).

### Configuración de instalación y filtros

- **FR-007**: The system MUST load installation configuration from a YAML file at startup (path given by `INSTALLATION_CONFIG`), validated against a schema; an invalid file MUST fail startup rather than run with partial configuration.
- **FR-008**: The system MUST upsert, at startup, the `fuentes` declared in the installation configuration, idempotently (no duplicates on repeated restarts).
- **FR-009**: The installation configuration MUST support declaring filters of type `seleccion` (one or more discrete values) and `rango_numerico` (min/max) over keys of `documentos.metadata`.
- **FR-010**: `GET /v1/config` MUST expose the declared filters and their labels for the running installation.
- **FR-011**: `GET /v1/search` MUST accept `filtro.<clave>=valor` parameters for each declared filter, in addition to the existing `date_from`, `date_to` and `mode` parameters.
- **FR-012**: WHEN a search request includes a filter key not declared in the installation configuration, the system SHALL respond with HTTP 422 and MUST NOT execute the underlying query.
- **FR-013**: Filter-to-SQL translation MUST be implemented as a pure, reusable function `aplicar_filtros(consulta, filtros, config)`, independent of the HTTP layer, so it can be reused by subscriptions in a later stage.

### Migración y regresión

- **FR-014**: The database migration for this stage MUST be reversible, with a tested `downgrade` path, per the company constitution on schema changes.
- **FR-015**: The migration MUST backfill `fuentes` from existing `jurisdiccion` values and `documentos.metadata.provincia` from the corresponding source data, without discarding any existing row.
- **FR-016**: The Boletín adapter MUST continue to satisfy every previously passing MVP acceptance behaviour after the rename: idempotent ingestion, date filters, hybrid search (`semantic`/`hybrid`/`all`), feedback, and the Docker smoke test.
- **FR-017**: The system core (models, ingestion, search, migrations) MUST NOT reference `Boletin`-specific names (`Boletin`, `boletin_id`, `identificador_oficial`, `url_oficial`); only the Boletín-specific adapter, seed data and installation configuration MAY.

## Success Criteria

- **SC-001**: `grep -ril boletin backend/src/db backend/src/api backend/src/ingestor` (excluding the Boletín adapter module and `seed/`) returns 0 matches.
- **SC-002**: An integration test ingests documents from 2 distinct `fuentes` into the same instalación and both are returned by an unfiltered search — 100% of documents from both sources present.
- **SC-003**: Renaming a declared filter's label or adding a new declared filter (e.g. `provincia` → `municipio`) requires changes to `installation.yaml` only — 0 changes to files under `backend/src/`, verified by a demonstration commit touching only the config file.
- **SC-004**: 100% of the pre-existing MVP test suite (~46 tests, migrated for the rename) passes after the change.
- **SC-005**: An end-to-end test filtering by `municipio=Carlos Paz` returns 0 results tagged `Noetinger`.
- **SC-006**: An `upgrade` → `downgrade` → `upgrade` cycle of the new migration, run against a database seeded with example data, completes with exit code 0 and no data loss (mirrors the existing `test_migrations.py` pattern).

## Clarifications

- **Q**: ¿Se reforma este repositorio o se crea uno nuevo? **A**: Se reforma este repositorio, sin capa de compatibilidad temporal para `/v1/boletines`, porque nada externo lo consume todavía. (2026-09-18)
- **Q**: ¿Qué modelo de filtros usa una instalación? **A**: `metadata` en JSONB con índice GIN; cada instalación declara sus filtros (`seleccion`, `rango_numerico`) en `installation.yaml`; el núcleo solo trae fecha y fuente. (2026-09-18)
- **Q**: ¿Dónde se implementa "este cliente solo ve Córdoba"? **A**: Etapa 3 (usuarios y suscripciones), reutilizando `aplicar_filtros` como filtro obligatorio del usuario; queda fuera del alcance de esta etapa. (2026-09-18)
- **Q**: ¿En qué orden se construyen las etapas de la generalización? **A**: Por capas, como en el spec original — núcleo genérico, ingesta operativa, clientes y suscripciones, notificaciones, segundo vertical — asumiendo el riesgo de validar el contrato con un solo vertical hasta el final. (2026-09-18)
- **Q**: ¿El índice HNSW sobre embeddings puede afectar el recall al combinarlo con los nuevos filtros de metadata? **A**: Riesgo real, anotado en la sección 10.6 del design spec; se cubre con una prueba de recall con filtro selectivo antes de cerrar esta etapa, y queda pendiente confirmar la versión de pgvector instalada. (2026-09-18)
