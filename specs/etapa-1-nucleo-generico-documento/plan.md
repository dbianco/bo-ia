# Plan: Etapa 1 — Núcleo genérico (Documento)

Framework: spec-kit (track default)
Feature ID: f_01m37e47q8s40qfzv53n5bpa1y
Fuente: `spec.md` de esta feature y `docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md` (v0.2), sección 8

## Technical Context

- **Lenguaje y versión:** Python 3.12, mismo backend consolidado (Ingestor + Procesador + API) del MVP.
- **Dependencias principales:** se mantienen FastAPI, SQLAlchemy + psycopg, pgvector, `sentence-transformers`, Alembic. `pydantic-settings` ya es dependencia declarada mas nunca usada; esta etapa la pone en uso para validar `installation.yaml`. Se agrega `PyYAML` (nueva dependencia, MIT, para parsear el YAML de configuración de instalación; no hay alternativa en la librería estándar).
- **Almacenamiento:** mismo PostgreSQL 16 + pgvector. `documentos.metadata` se tipa `JSONB` (no `JSON`) con un índice GIN, para soportar el operador `@>` que usa `aplicar_filtros`. `fragmentos.metadata_` (columna `JSON` sin uso) queda sin tocar; está fuera del alcance de esta etapa.
- **Herramientas de testing:** pytest, igual que el MVP. Se extiende `test_migrations.py` con el ciclo `upgrade → downgrade → upgrade` de la migración nueva, en vez de crear un archivo de test de migraciones aparte.
- **Plataforma objetivo:** sin cambios — Docker Compose local en macOS/Windows, CPU-only.
- **Objetivos de performance y restricciones:** sin cambios respecto al MVP (SC-004 original); los filtros nuevos se agregan a una consulta que ya cumple el presupuesto de 2s, y se cubren con la misma suite de tests de rendimiento existente (no se agregan objetivos nuevos, no hay evidencia todavía de que haga falta).

## Constitution Check

- **Sin datos personales en logs:** sin cambios; esta etapa no agrega autenticación ni campos de usuario. Los valores de `metadata` (provincia, municipio, organismo) son datos públicos de la fuente, no datos personales.
- **Timeout y retry en llamadas HTTP salientes:** no aplica; `installation.yaml` se lee de un archivo local montado en el contenedor, no hay una llamada de red nueva.
- **Migraciones de esquema reversibles con rollback probado:** la migración de esta etapa (rename `boletines`→`documentos`, tabla `fuentes`, columnas nuevas, backfill) se escribe como una única revisión Alembic con `downgrade` completo, probada con el mismo patrón `upgrade → downgrade → upgrade` que ya usa `test_migrations.py` (SC-006).
- **Cambios de API pública aditivos dentro de una versión mayor:** **desviación consciente**, ya decidida y registrada en las Clarifications de `spec.md`: `POST /v1/boletines` se renombra a `POST /v1/documentos` sin capa de compatibilidad, porque la API todavía no tiene consumidores externos (nada fuera de este repo la llama). Los campos nuevos de `GET /v1/search` (`filtro.<clave>`) y el endpoint nuevo `GET /v1/config` sí son aditivos.
- **Secretos desde el entorno:** sin cambios; `INSTALLATION_CONFIG` es una ruta de archivo, no un secreto, y se documenta en `.env.example` igual que las demás variables.
- **Tests en CI antes de mergear:** sin cambios; el mismo `ci.yml` corre lint y la suite de pytest, ahora ampliada.
- **Accesibilidad:** los controles de filtro que genera la web a partir de `GET /v1/config` usan `<select>`/`<input>` nativos con `<label>`, siguiendo el mismo patrón ya verificado del formulario de fecha.

## Project Structure

Lista final real, actualizada tras `implement` (igual que se hizo en la feature del MVP).

Modificados:

- `backend/pyproject.toml`
- `backend/src/db/models.py`
- `backend/src/api/ingest.py`
- `backend/src/api/search.py`
- `backend/src/api/main.py`
- `backend/src/api/deps.py`
- `backend/src/seed/seed.py`
- `web/app.py`
- `web/templates/search.html`
- `web/templates/_resultados.html`
- `docker-compose.yml`
- `.env.example`
- `README.md`
- `backend/tests/conftest.py`
- `backend/tests/test_migrations.py`
- `backend/tests/api/test_ingest.py`
- `backend/tests/api/test_search.py`
- `backend/tests/api/test_search_hybrid.py`
- `backend/tests/api/test_feedback.py`
- `backend/tests/ingestor/test_ingestor.py`

Nuevos:

- `backend/src/db/migrations/versions/a00b1eb51d18_generalize_documentos_fuentes.py`
- `backend/src/ingestor/contract.py` (dataclass `DocumentoNormalizado`, contrato completo de ingesta: `ingerir_documento`, antes dividido entre `ingest.py` y `seed.py`)
- `backend/src/ingestor/adapters/__init__.py`
- `backend/src/ingestor/adapters/boletin.py` (adaptador específico del Boletín)
- `backend/src/config/__init__.py`
- `backend/src/config/installation.py` (modelo pydantic, loader de `installation.yaml` y `upsert_fuentes`)
- `backend/src/search/__init__.py`
- `backend/src/search/filters.py` (`aplicar_filtros`, función pura)
- `backend/src/api/config.py` (`GET /v1/config`)
- `installation.yaml` (configuración de instalación del vertical Boletín, raíz del repo)
- `backend/src/seed/sample_documentos.json` (reemplaza a `sample_boletines.json`; incluye dos municipios para SC-002/SC-005)
- `backend/tests/config/__init__.py`, `backend/tests/config/test_installation.py`
- `backend/tests/search/__init__.py`, `backend/tests/search/test_filters.py`
- `backend/tests/api/test_config.py`
- `backend/tests/api/test_search_filters.py`
- `backend/tests/api/test_search_recall.py` (riesgo 10.6: verifica el estado real de `hnsw.iterative_scan` y un caso de filtro selectivo con 200 no-matches)

Eliminados:

- `backend/src/seed/sample_boletines.json` (reemplazado por `sample_documentos.json`)
- `backend/src/ingestor/ingest.py` (su lógica quedó absorbida por `ingestor/contract.py`; mantenerlo hubiera duplicado la idempotencia y dejado código muerto)

## Research

- **Formato de `installation.yaml`:** YAML sobre JSON, porque es el formato que la propuesta original ya usa en sus ejemplos (sección 3.4 del design spec) y es más legible para editar a mano. Se agrega `PyYAML` como dependencia nueva (razón de una línea para el PR: no hay parser YAML en la librería estándar; MIT, compatible).
- **`documentos.metadata` como `JSONB` con índice GIN:** elegido sobre mantenerlo `JSON` porque `aplicar_filtros` necesita el operador de contención `@>`, que Postgres solo indexa eficientemente sobre `jsonb`, no sobre `json`. Alcanza con el índice GIN por defecto (sin `jsonb_path_ops`), porque los filtros son de igualdad/pertenencia, no de path queries complejas.
- **`aplicar_filtros` como módulo puro (`backend/src/search/filters.py`):** sin importar SQLAlchemy `Session` ni FastAPI, para que la Etapa 3 lo reutilice desde suscripciones sin acoplarse a la capa HTTP (FR-013).
- **Extracción de `ingerir_documento` (`backend/src/ingestor/contract.py`):** hoy la lógica de fragmentar y generar embeddings está duplicada entre `backend/src/api/ingest.py` y `backend/src/seed/seed.py`. Se extrae una única función y un contrato `DocumentoNormalizado`, y el adaptador del Boletín (`backend/src/ingestor/adapters/boletin.py`) traduce sus campos a ese contrato antes de llamarla.
- **Migración única y reversible:** en vez de varias migraciones pequeñas, una sola revisión Alembic agrupa el rename, la tabla `fuentes`, el backfill y los índices nuevos, para que el ciclo `upgrade → downgrade → upgrade` (SC-006) sea una sola operación de comprobar, siguiendo el patrón ya usado por `test_migrations.py`.
- **Pendiente de verificar antes de `verify`:** la versión de pgvector instalada en `pgvector/pgvector:pg16` (riesgo 10.6 del design spec — filtrar sobre el índice HNSW puede reducir el recall). Se agrega como tarea explícita en `tasks.md`, no se resuelve en esta fase de planificación.
