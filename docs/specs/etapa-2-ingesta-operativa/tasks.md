# Tasks: Etapa 2 — Ingesta operativa

Framework: spec-kit (track default)
Feature ID: f_01m37nm2axpsc7gyjt6sq9vktt
Fuente: `plan.md` de esta feature (Project Structure y Research)

Orden: toda dependencia aparece antes que la tarea que depende de ella. `[P]` marca tareas que pueden hacerse en paralelo (no dependen entre sí y tocan archivos distintos).

## Tasks

### Setup

- [x] T001 Agregar `scrapy`, `apscheduler` y `pypdf` como dependencias (versiones confirmadas contra PyPI) en `backend/pyproject.toml`
- [x] T002 [P] Crear fixtures del BOP (`index.html`, `anuncio_ok.pdf`, `anuncio_corrupto.pdf`) en `backend/tests/fixtures/bop_cordoba/`, basados en la estructura observada en el PoC
- [x] T003 [P] Agregar el marker `live` (mismo patrón que `slow`/`docker`) en `backend/pyproject.toml`

### Modelo de datos y migración

- [x] T004 Agregar el modelo `EjecucionFuente` (tabla `ejecuciones_fuente`: `fuente_id`, `inicio`, `fin`, `estado`, `descubiertos`, `nuevos`, `existentes`, `errores`, `version_conector`, `detalle_errores` JSONB) en `backend/src/db/models.py` (FR-001), depends on T001
- [x] T005 Escribir la migración Alembic que crea `ejecuciones_fuente`, con `downgrade` completo, en `backend/src/db/migrations/versions/`, depends on T004
- [x] T006 Extender el ciclo `upgrade → downgrade → upgrade` de `backend/tests/test_migrations.py` para la nueva revisión, depends on T005

### Interfaz de conector y runner (TDD)

- [x] T007 [P] Escribir tests que fallen para `ejecutar_conector` (cuenta `nuevos`/`existentes`/`errores`, invariante `descubiertos = nuevos + existentes + errores` [SC-003], un error individual no pierde el resto de la ejecución [FR-003]) usando un conector fake, en `backend/tests/connectors/test_runner.py`, depends on T005
- [x] T008 Implementar `Conector` (Protocol) y `ErrorDescubrimiento` (dataclass) en `backend/src/connectors/protocol.py` (FR-004, FR-005), depends on T007
- [x] T009 Implementar `ejecutar_conector(session, embedder, fuente, conector, config, version_conector)` en `backend/src/connectors/runner.py` (FR-001, FR-002, FR-003), depends on T008

### Conector del BOP: extracción de PDF

- [x] T010 [P] Escribir tests que fallen para `extraer_texto_pdf` (texto real desde `anuncio_ok.pdf`; `anuncio_corrupto.pdf` levanta una excepción clara) en `backend/tests/connectors/test_bop_cordoba.py`, depends on T002
- [x] T011 Implementar `extraer_texto_pdf` con `pypdf` en `backend/src/connectors/bop_cordoba/pdf.py`, depends on T010

### Conector del BOP: spider y conector

- [x] T012 [P] Escribir un test que falle: el conector del BOP contra el fixture `file://` produce el número de documentos del índice, con texto extraído del PDF (SC-001), en `backend/tests/connectors/test_bop_cordoba.py`, depends on T002, depends on T011
- [x] T013 [P] Escribir un test que falle: un PDF corrupto entre los N produce exactamente 1 `ErrorDescubrimiento` y N-1 documentos normalizados (SC-004), en `backend/tests/connectors/test_bop_cordoba.py`, depends on T012
- [x] T014 Implementar el spider `BopCordobaSpider` (descubre anuncios, sigue el link al PDF con su propio request, extrae texto, emite el item o un item de error) en `backend/src/connectors/bop_cordoba/spider.py` (FR-006, FR-007, FR-008, FR-009), depends on T011
- [x] T015 Implementar `ConectorBopCordoba` (corre el spider en un subproceso `multiprocessing`, lee el feed `jsonlines`, traduce cada línea a `DocumentoNormalizado` o `ErrorDescubrimiento`) en `backend/src/connectors/bop_cordoba/connector.py`, depends on T014
- [x] T016 Registrar el conector bajo la clave `bop-cordoba-scrapy` en `backend/src/connectors/registry.py`, depends on T015

### Idempotencia de punta a punta

- [x] T017 Escribir un test que falle: re-correr `ejecutar_conector` con `ConectorBopCordoba` contra el mismo fixture produce 0 nuevos, 100% existentes (SC-002), en `backend/tests/connectors/test_bop_cordoba.py`, depends on T009, depends on T016

### Scheduler

- [x] T018 [P] Escribir tests que fallen para el scheduler: dispara un conector fake en un intervalo acelerado sin intervención manual (SC-005); una fuente sin conector declarado no programa nada (FR-012), en `backend/tests/scheduler/test_scheduler.py`, depends on T009
- [x] T019 Implementar `iniciar_scheduler`/`detener_scheduler` con APScheduler `BackgroundScheduler` en `backend/src/scheduler/__init__.py` (FR-010), depends on T018
- [x] T020 Conectar el scheduler al `lifespan` de FastAPI (arranca al iniciar, se detiene al apagar) en `backend/src/api/main.py`, depends on T019, depends on T016

### Ejecución manual (API)

- [x] T021 [P] Escribir tests que fallen para `POST /v1/fuentes/{clave}/ejecutar` (dispara una ejecución y devuelve su resultado; 404 si la fuente no existe o no tiene conector configurado) en `backend/tests/api/test_fuentes.py` (FR-011), depends on T009
- [x] T022 Implementar el endpoint en `backend/src/api/fuentes.py`, depends on T021

### Configuración

- [x] T023 Extender `FuenteConfig`/`InstallationConfig` en `backend/src/config/installation.py` para aceptar un bloque `conector` opcional (`tipo`, `config`, `frecuencia_minutos`) (FR-013), depends on T016
- [x] T024 Declarar el conector `bop-cordoba-scrapy` para la fuente `cordoba-provincial` en `installation.yaml`, depends on T023

### Pulido y verificación

- [x] T025 [P] Escribir un test marcado `live` (excluido por defecto y de CI) que corre el conector real contra `bop.dipucordoba.es`, para chequeo manual ocasional, en `backend/tests/connectors/test_bop_cordoba_live.py` (SC-006), depends on T016
- [x] T026 Actualizar `README.md` (el scheduler corre dentro del backend, cómo declarar un conector, cómo disparar una ejecución manual), depends on T022, depends on T024
- [x] T027 Correr la suite completa (migración, runner, PDF, conector BOP con fixtures, idempotencia, scheduler, endpoint manual) y confirmar cada escenario de aceptación y criterio de éxito de `spec.md`; registrar los resultados como evidencia para la fase `verify`, depends on T006, depends on T013, depends on T017, depends on T020, depends on T022, depends on T024, depends on T025, depends on T026
