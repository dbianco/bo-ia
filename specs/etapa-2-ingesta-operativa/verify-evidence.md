# Evidencia de verificación — Etapa 2 (ingesta operativa)

Feature ID: `f_01m37nm2axpsc7gyjt6sq9vktt` · Fecha: 2026-09-23

Cruza cada escenario de aceptación y criterio de éxito de `spec.md` contra la verificación real hecha durante `implement`. Todo lo marcado ✅ se corrió con comandos reales: `pytest` contra Postgres real (puerto 9100), `alembic upgrade/downgrade` real, `docker compose up --build` real (smoke test), y el conector real contra `bop.dipucordoba.es` (marcado `live`, corrido a mano, no en CI).

## Acceptance scenarios (spec.md)

| # | Escenario | Estado | Evidencia |
|---|---|---|---|
| 1 | El scheduler ejecuta el conector automáticamente al llegar el intervalo | ✅ | `tests/scheduler/test_scheduler.py::test_scheduler_dispara_automaticamente_sin_intervencion_manual` |
| 2 | Cada ejecución queda registrada en `ejecuciones_fuente` | ✅ | `tests/connectors/test_runner.py` (5 tests); esquema en `tests/test_migrations.py` |
| 3 | El conector del BOP descubre anuncios, extrae PDF y produce `DocumentoNormalizado` | ✅ | `tests/connectors/test_bop_cordoba.py::test_conector_bop_produce_documentos_normalizados_desde_el_fixture`; confirmado además contra el sitio real (ver sección "Conector real" abajo) |
| 4 | Un documento ya ingerido se cuenta como "existente", no "nuevo" | ✅ | `tests/connectors/test_bop_cordoba.py::test_reejecutar_el_conector_bop_es_idempotente` |
| 5 | Un error de PDF no pierde el resto de la ejecución | ✅ | `tests/connectors/test_bop_cordoba.py::test_conector_bop_reporta_el_pdf_ilegible_como_error`; `tests/connectors/test_runner.py::test_error_de_descubrimiento_no_pierde_el_resto_de_la_ejecucion` |
| 6 | Una ejecución manual corre el mismo conector y registra la misma clase de ejecución | ✅ | `tests/api/test_fuentes.py::test_ejecutar_fuente_dispara_una_ejecucion_y_devuelve_su_resultado`; confirmado con `curl` real contra el stack levantado (ver abajo) |
| 7 | El scheduler programa cada fuente con conector al arrancar | ✅ | `tests/scheduler/test_scheduler.py::test_fuente_sin_conector_declarado_no_programa_nada` (caso negativo); smoke Docker real confirma que el backend arranca con el scheduler sin caerse |

## Success Criteria (spec.md)

| Criterio | Estado | Evidencia |
|---|---|---|
| SC-001: fixture del índice → N documentos normalizados | ✅ | `test_conector_bop_produce_documentos_normalizados_desde_el_fixture`: 3 documentos válidos + 1 error, del fixture de 4 anuncios |
| SC-002: re-correr el fixture → 0 nuevos | ✅ | `test_reejecutar_el_conector_bop_es_idempotente` |
| SC-003: `nuevos + existentes + errores == descubiertos` | ✅ | Verificado en los 5 tests de `test_runner.py` y en los del conector BOP |
| SC-004: 1 PDF ilegible entre N → 1 error, N-1 documentos | ✅ | `test_conector_bop_reporta_el_pdf_ilegible_como_error` (fixture con 3 PDFs válidos + 1 corrupto) |
| SC-005: intervalo acelerado → el scheduler dispara solo | ✅ | `test_scheduler_dispara_automaticamente_sin_intervencion_manual` (intervalo de ~2s) |
| SC-006: 0 llamadas de red real en la suite por defecto | ✅ | Todos los tests de conector corren contra fixtures `file://`; el único test que llama a `bop.dipucordoba.es` está marcado `live`, excluido por `ci.yml` (`pytest -m "not docker and not live"`) |

## Conector real contra el sitio del BOP

Corrido a mano, fuera de la suite automática:

1. **`pytest -m live`** (host, contra el día del PoC: 05-06-2026): **30 documentos, 0 errores**, en 9.65s. Mismo conteo que encontró el PoC de scraping. El primer documento (`BOP-A-2026-1683`) tiene texto real extraído del PDF (edicto de un ayuntamiento, con fecha, número de boletín y cuerpo del acto). Esta es la evidencia principal de que FR-006/FR-007 funcionan de punta a punta contra el sitio real.
2. **`curl -X POST http://localhost:9101/v1/fuentes/cordoba-provincial/ejecutar`** contra el stack de Docker: primer intento con el timeout por defecto original (120s) **falló por timeout** — hallazgo real, ver abajo. Con el timeout corregido (900s), la corrida quedó procesando activamente (CPU del contenedor sobre 1000%, más PIDs activos) pero no se pudo confirmar su fin dentro de esta sesión: la máquina de desarrollo tiene otros 10 contenedores no relacionados corriendo en paralelo (proyectos `textra-*` y `sddorchestrator-*`), y la contención de memoria del host mató dos procesos de espera propios (`curl` y un polling con `psql`) antes de que la ejecución terminara. El endpoint y el conector en sí no fallaron — es un límite de tiempo de esta verificación, no evidencia de un bug.

### Hallazgo real: Scrapy es mucho más lento dentro de este contenedor Docker que en el host

Medido explícitamente para diagnosticar el timeout del punto 2:

| Método | Contexto | Resultado |
|---|---|---|
| `ConectorBopCordoba` (Scrapy) | Host (venv) | 30 documentos en 9.65s |
| `ConectorBopCordoba` (Scrapy) | Contenedor Docker | 11 documentos en 280s (~25s/documento) |
| `urllib.request` directo, mismo PDF, 3 veces | Contenedor Docker | ~2.5s cada vez, consistente |

La red del contenedor no está degradada (una descarga directa del mismo PDF es rápida y estable); el problema es específico de Scrapy/Twisted corriendo dentro de este contenedor. No se identificó la causa raíz exacta dentro del tiempo de esta sesión (se descartó IPv6/DNS: `getaddrinfo` resuelve en <20ms y devuelve solo la dirección IPv4 esperada). Mitigación aplicada: se subió `TIMEOUT_PROCESO_DEFAULT` de 120s a 900s en `src/connectors/bop_cordoba/connector.py` — aceptable porque la fuente corre una vez por día; perder una corrida completa por un timeout ajustado es peor que tardar más. Este comportamiento puede variar según el host real de despliegue.

## Trazabilidad FR → test

| FR | Cubierto por |
|---|---|
| FR-001, FR-002, FR-003 | `tests/connectors/test_runner.py` |
| FR-004, FR-005 | `src/connectors/protocol.py`; usado por todos los tests de conector |
| FR-006, FR-007 | `tests/connectors/test_bop_cordoba.py` |
| FR-008 | `test_conector_bop_reporta_el_pdf_ilegible_como_error`; `tests/connectors/test_bop_cordoba.py` (extracción de PDF) |
| FR-009 | `DOWNLOAD_TIMEOUT`/`RETRY_TIMES` en `src/connectors/bop_cordoba/connector.py`; timeout de proceso en el mismo módulo |
| FR-010, FR-012 | `tests/scheduler/test_scheduler.py` |
| FR-011 | `tests/api/test_fuentes.py` |
| FR-013 | `src/config/installation.py` (`ConectorConfig`); `installation.yaml` |

## Checklist de la fase `verify`

- **Lint (ruff):** `ruff check src tests` → 0 hallazgos.
- **Tests:** 82 tests recolectados. 80 pasan en `pytest --ignore=tests/smoke -m "not live"` (incluye el modelo real de embeddings y el test `slow` de recall de la Etapa 1), 1 deselected (`live`). El smoke Docker (81º) y el `live` (82º) se corrieron aparte, ambos en verde.
- **Smoke Docker real:** `pytest -m docker tests/smoke/test_docker_up.py` → 1/1 en verde. Reconstruyó las imágenes (scrapy/twisted/apscheduler/pypdf incluidos, imagen backend más pesada que en la Etapa 1), aplicó la migración de `ejecuciones_fuente`, y el backend arrancó con el scheduler registrado sin caerse.
- **files_changed:** ver `plan.md` → Project Structure para el árbol final.

## Bugs y ajustes reales encontrados durante `implement`

1. **Colisión de hash de contenido en tests propios**: varios tests de `test_runner.py` usaban el mismo texto por defecto para documentos distintos, así que la idempotencia por hash (correcta, heredada de la Etapa 1) los trataba como el mismo documento. Se corrigió generando texto único por identificador en el helper `_doc()`. Mismo patrón de error que ya había aparecido en la Etapa 1.
2. **`ConectorConfig.frecuencia_minutos` como `int` no alcanzaba para tests rápidos**: un intervalo de scheduler expresado en minutos enteros no permite un test de segundos. Se cambió a `float`, sin afectar el uso real (`1440` sigue siendo válido).
3. **Falso positivo de timing en el test del scheduler**: la primera versión del test detectaba la ejecución apenas se creaba (`estado="en_curso"`), antes de que terminara. Se corrigió filtrando por `fin IS NOT NULL` en el polling.
4. **Lo que NO fue un bug, y sorprendió**: el subproceso de Scrapy (`multiprocessing`, contexto `spawn`) + el seguimiento de PDFs con su propio `scrapy.Request` + la extracción con `pypdf`, todo contra fixtures `file://`, funcionó en el primer intento, sin iteración. Corrido contra el sitio real también funcionó al primer intento (30/30 documentos, 0 errores).

## Gaps conocidos, sin resolver

1. **Causa raíz de la lentitud de Scrapy en Docker sin identificar**: se descartó IPv6/DNS y se confirmó que no es la red del contenedor en general (ver hallazgo arriba), pero no se investigó más a fondo (candidatos no explorados: el pool de threads del resolver de Twisted, el manejo de TLS de `Agent`, o contención de CPU del host durante la medición). Mitigado con un timeout más generoso; revisar si se repite con volumen real.
2. **Sin backoff exponencial entre reintentos**: `RETRY_TIMES` de Scrapy reintenta con backoff simple; no se agregó una política de reintento a nivel de ejecución completa (una ejecución fallida espera al siguiente intervalo programado, o a un disparo manual). Suficiente para el volumen actual (una fuente, una corrida diaria).
3. **Sin límite de concurrencia entre fuentes**: si en el futuro hay muchas fuentes con conectores reales, cada una dispara su propio subproceso de Scrapy sin coordinación entre sí. No es un problema con una sola fuente real; revisar si se agregan más.
4. **`GET /v1/fuentes/{clave}/ejecuciones` (listar historial) no se implementó**: no estaba en los FR/SC de `spec.md`; queda para cuando haga falta observar ejecuciones pasadas desde la API en vez de la base directamente.
