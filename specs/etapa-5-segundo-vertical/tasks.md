# Tasks: Etapa 5 — Segundo vertical

Framework: spec-kit (track default)
Feature ID: f_01m39qv30dtyfw4mhypkdt2ysb
Fuente: `plan.md` de esta feature (Project Structure y Research)

Orden: toda dependencia aparece antes que la tarea que depende de ella. `[P]` marca tareas que pueden hacerse en paralelo (no dependen entre sí y tocan archivos distintos).

## Tasks

### Setup y fixtures

- [x] T001 [P] Descargar una muestra real acotada de `Convocatorias.csv` (encabezado + ~50 filas reales, incluida al menos una con `Monto_Estimado` no numérico/vacío) y guardarla como `backend/tests/fixtures/comprar_gob_ar/convocatorias_sample.csv`
- [x] T002 [P] Descargar un PDF real de la 4° Sección de `boletinoficial.cba.gov.ar` y guardarlo como `backend/tests/fixtures/boletin_cba/4_Secc_sample.pdf`
- [x] T003 [P] Agregar el marker `live` para los tests nuevos que pegan contra datos.gob.ar/boletinoficial.cba.gov.ar reales, reusando la configuración ya existente en `backend/pyproject.toml` (sin cambios si el marker ya está declarado desde la Etapa 2)

### Conector `comprar-gob-ar-csv` (TDD)

- [x] T004 Escribir tests que fallen para el parseo de una fila del CSV a `DocumentoNormalizado` (mapeo de columnas, `monto` parseado desde `"1,735,400.00"`, `jurisdiccion="nacional"` en metadata) y para una fila con `Monto_Estimado` no parseable (se ingiere igual, sin `monto` en metadata — FR-003), contra el fixture `file://`, en `backend/tests/connectors/test_comprar_gob_ar.py`, depends on T001
- [x] T005 Escribir un test que falle: el filtro por `anio_desde` descarta filas de años anteriores sin fallar la ejecución, en `backend/tests/connectors/test_comprar_gob_ar.py`, depends on T004
- [x] T006 Implementar `ConectorComprarGobAr` (`descubrir`: descarga el CSV vía `urllib.request` con timeout, parsea en streaming con `csv.DictReader`, filtra por `anio_desde`, produce `DocumentoNormalizado` por fila) en `backend/src/connectors/comprar_gob_ar/connector.py` (FR-001, FR-002, FR-003, FR-004), depends on T005
- [x] T007 Registrar el conector bajo la clave `comprar-gob-ar-csv` en `backend/src/connectors/registry.py`, depends on T006

### Conector `boletin-cba-pdf-diario` (TDD)

- [x] T008 Escribir tests que fallen para la construcción de la URL de una sección/fecha y la extracción de su texto (reusando `extraer_texto_pdf` de `src/connectors/bop_cordoba/pdf.py`) contra el fixture `file://`, en `backend/tests/connectors/test_boletin_cba.py`, depends on T002
- [x] T009 Escribir un test que falle: una sección no publicada (404) para una fecha se registra como `ErrorDescubrimiento` de esa (fecha, sección) puntual, sin abortar el resto (FR-007), en `backend/tests/connectors/test_boletin_cba.py`, depends on T008
- [x] T010 Implementar `ConectorBoletinCba` (`descubrir`: para cada sección configurada, construye la URL, descarga vía `urllib.request` con timeout/reintentos y User-Agent genérico, extrae texto, produce `DocumentoNormalizado` con `identificador_externo="{sección}_Secc_{ddmmyy}"`) en `backend/src/connectors/boletin_cba/connector.py` (FR-005, FR-006, FR-008, FR-009), depends on T009
- [x] T011 Registrar el conector bajo la clave `boletin-cba-pdf-diario` en `backend/src/connectors/registry.py`, depends on T010, depends on T007

### Instalación "Licitaciones Argentina"

- [x] T012 Escribir `installation-licitaciones.yaml` (fuentes `comprar-ar-nacional` y `cba-provincial-licitaciones` con sus conectores y config; filtros declarados `organismo` y `monto`) (FR-010), depends on T011
- [x] T013 [P] Escribir `.env.licitaciones.example` (puertos propios, `POSTGRES_DB` propio, mismo `INSTALLATION_CONFIG` interno) y `docker-compose.licitaciones.override.yml` (monta `installation-licitaciones.yaml` en vez de `installation.yaml`) (FR-011), depends on T012

### Corrección de `cordoba-provincial` (boletines)

- [x] T014 Actualizar `installation.yaml` (boletines) para que `cordoba-provincial` use el conector `boletin-cba-pdf-diario` contra `boletinoficial.cba.gov.ar`, configurado para las 5 secciones, en vez de `bop-cordoba-scrapy` (FR-012), depends on T011

### Verificación real de punta a punta

- [x] T015 [P] Escribir tests marcados `live` (excluidos por defecto y de CI) que corren ambos conectores contra los sitios/datasets reales, para chequeo manual ocasional, en `backend/tests/connectors/test_comprar_gob_ar_live.py` y `backend/tests/connectors/test_boletin_cba_live.py` (SC-001, SC-002, SC-007), depends on T007, depends on T011
- [x] T016 Levantar el segundo stack Docker real (`docker compose -p bo-ia-licitaciones --env-file .env.licitaciones -f docker-compose.yml -f docker-compose.licitaciones.override.yml up -d --build`) en paralelo al stack de boletines ya corriendo; confirmar 2 fuentes creadas (SC-003), disparar ambos conectores manualmente (`POST /v1/fuentes/{clave}/ejecutar`) y confirmar documentos reales ingeridos con `organismo`/`monto`/texto poblados, depends on T012, depends on T013, depends on T015
- [x] T017 Confirmar en real que `GET /v1/search?filtro.monto=...` filtra sobre los datos ingeridos en el stack de licitaciones (SC-004) y que el stack de boletines, corregido, sigue ingiriendo y buscando sin tocar auth/suscripciones/notificaciones (SC-005); confirmar aislamiento entre ambos stacks (SC-006), depends on T014, depends on T016
- [x] T018 Actualizar `README.md` (segundo vertical, cómo levantar el stack de licitaciones en paralelo, corrección de la fuente `cordoba-provincial`), depends on T017
- [x] T019 Correr la suite completa (ambos conectores con fixtures, registry, instalación) y confirmar cada escenario de aceptación y criterio de éxito de `spec.md`; registrar los resultados como evidencia para la fase `verify`, depends on T017, depends on T018
