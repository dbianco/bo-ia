# Tasks: MVP público de búsqueda semántica del Boletín Oficial

Framework: spec-kit (track default)
Feature ID: f_01m2npz2d7t6489bgwchqas3wm
Fuente: `plan.md` de esta feature (Project Structure y Technical Context)

Orden: toda dependencia aparece antes que la tarea que depende de ella. `[P]` marca tareas que pueden hacerse en paralelo (no dependen entre sí y tocan archivos distintos).

## Tasks

### Setup

- [ ] T001 Inicializar el proyecto Python del backend (dependencias: fastapi, sqlalchemy, psycopg, pgvector, sentence-transformers, alembic, pytest) en `backend/pyproject.toml`
- [ ] T002 [P] Escribir `.env.example` con las variables de entorno requeridas (credenciales de Postgres, puertos, ruta de caché del modelo) en `.env.example`
- [ ] T003 Escribir `docker-compose.yml` definiendo los servicios `db`, `backend` y `web` con volúmenes nombrados para los datos de Postgres y la caché del modelo de embeddings, depends on T001, depends on T002
- [ ] T004 [P] Escribir `backend/Dockerfile` (base Python 3.12, CPU-only, instala desde `pyproject.toml`), depends on T001
- [ ] T005 [P] Escribir `web/Dockerfile` (sirve la app Jinja2/htmx), depends on T001
- [ ] T006 [P] Inicializar Alembic en `backend/src/db/migrations/`, depends on T001

### Modelo de datos

- [ ] T007 Escribir la migración de Alembic que habilita pgvector y crea la tabla `boletines`, con su migración `down`, en `backend/src/db/migrations/`, depends on T006
- [ ] T008 Escribir la migración de Alembic que crea la tabla `fragmentos` con columna vectorial, con su migración `down`, en `backend/src/db/migrations/`, depends on T007
- [ ] T009 [P] Escribir la migración de Alembic que crea `tags` y `fragmento_tags`, con su migración `down`, en `backend/src/db/migrations/`, depends on T007
- [ ] T010 [P] Escribir la migración de Alembic que crea `valoraciones`, con su migración `down`, en `backend/src/db/migrations/`, depends on T007
- [ ] T011 Escribir un test de rollback que verifique que cada `up` tiene un `down` funcional en `backend/tests/test_migrations.py`, depends on T008, depends on T009, depends on T010

### Tests primero (TDD)

- [ ] T012 [P] Escribir tests que fallen para validación de ingesta, idempotencia y conservación del contenido original (FR-001, FR-002, FR-003, FR-006) en `backend/tests/ingestor/test_ingestor.py`, depends on T008
- [ ] T013 [P] Escribir tests que fallen para fragmentación y la garantía de al menos un fragmento (FR-004, FR-005, FR-007) en `backend/tests/ingestor/test_fragmenter.py`, depends on T008
- [ ] T014 [P] Escribir tests que fallen para generación de embeddings y el filtro de umbral de similitud (FR-015) en `backend/tests/processor/test_embeddings.py`, depends on T008
- [ ] T015 [P] Escribir tests que fallen para el endpoint de búsqueda: consulta en lenguaje natural, filtros de fecha, orden por relevancia, límite de resultados, metadatos de cita, lista vacía cuando no hay resultados confiables (FR-008, FR-009, FR-010, FR-011, FR-012, FR-013) en `backend/tests/api/test_search.py`, depends on T008
- [ ] T016 [P] Escribir tests que fallen para el endpoint de valoraciones (pulgar arriba/abajo) (FR-014) en `backend/tests/api/test_feedback.py`, depends on T010
- [ ] T017 [P] Escribir un smoke test que falle, que levante `docker compose up` y ejercite la búsqueda contra los datos de ejemplo (FR-016, FR-017, SC-006) en `backend/tests/smoke/test_docker_up.py`, depends on T003

### Implementación

- [ ] T018 [P] Implementar validación de ingesta, hash de contenido e idempotencia en `backend/src/ingestor/ingest.py`, depends on T012
- [ ] T019 [P] Implementar la fragmentación de texto con tamaño y solapamiento configurables en `backend/src/ingestor/fragmenter.py`, depends on T013
- [ ] T020 [P] Implementar el proveedor de embeddings que envuelve `Qwen/Qwen3-Embedding-0.6B` vía `sentence-transformers`, con soporte de caché de modelo, en `backend/src/processor/embeddings.py`, depends on T014
- [ ] T021 Implementar el filtro de umbral de similitud aplicado sobre los resultados ordenados en `backend/src/processor/threshold.py`, depends on T020
- [ ] T022 Implementar el endpoint de búsqueda (`GET /v1/search`), conectando filtros de fecha, ranking, el filtro de umbral y el límite de resultados, en `backend/src/api/search.py`, depends on T015, depends on T019, depends on T021
- [ ] T023 Implementar el endpoint de ingesta (`POST /v1/boletines`) en `backend/src/api/ingest.py`, depends on T012, depends on T018, depends on T019
- [ ] T024 [P] Implementar el endpoint de valoraciones (`POST /v1/valoraciones`) en `backend/src/api/feedback.py`, depends on T016
- [ ] T025 Escribir el script de seed que carga `backend/src/seed/sample_boletines.json` al primer arranque del backend si `boletines` está vacía, depends on T023

### Interfaz web

- [ ] T026 Implementar la página de búsqueda en Jinja2 (campo de consulta, fecha desde/hasta, lista de resultados) en `web/templates/search.html`, depends on T022
- [ ] T027 Agregar los controles htmx de pulgar arriba/pulgar abajo en cada resultado, conectados al endpoint de valoraciones, en `web/templates/search.html`, depends on T024, depends on T026

### Pulido y verificación

- [ ] T028 Escribir el workflow de CI que corre pytest en cada push y pull request en `.github/workflows/ci.yml`, depends on T012, depends on T013, depends on T014, depends on T015, depends on T016, depends on T017
- [ ] T029 [P] Escribir una checklist manual de accesibilidad (navegación por teclado, controles etiquetados) para la página de búsqueda contra WCAG 2.1 AA en `backend/tests/manual/accessibility-checklist.md`, depends on T026, depends on T027
- [ ] T030 Actualizar `README.md` con instrucciones de arranque (`docker compose up --build`, datos de seed, cómo correr los tests) en `README.md`, depends on T003, depends on T025, depends on T028
- [ ] T031 Correr la suite completa de tests y el smoke test, confirmar que cada escenario de aceptación y criterio de éxito de `spec.md` se cumple, y registrar los resultados como evidencia para la fase `verify`, depends on T022, depends on T023, depends on T024, depends on T025, depends on T026, depends on T027, depends on T028, depends on T029, depends on T030
