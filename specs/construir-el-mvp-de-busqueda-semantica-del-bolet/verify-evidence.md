# Evidencia de verificación — MVP (T031)

Feature ID: `f_01m2npz2d7t6489bgwchqas3wm` · Fecha: 2026-09-16

Cruza cada escenario de aceptación y criterio de éxito de `spec.md` contra la verificación real hecha durante `implement`. Todo lo marcado ✅ se corrió con comandos reales (no simulado): tests automatizados, `docker compose up` real, `curl` contra los servicios levantados, y una corrida de CI en GitHub Actions.

## Acceptance scenarios (spec.md)

| # | Escenario | Estado | Evidencia |
|---|---|---|---|
| 1 | Búsqueda en lenguaje natural devuelve fragmentos relevantes ordenados, con fecha/id/link | ✅ | `tests/api/test_search.py` (4 tests); verificado además con `curl` real contra Docker: consulta "presupuesto provincial" devuelve `BO-DEMO-0001` con similitud 0.7343 |
| 2 | Filtro de fecha desde/hasta acota los resultados | ✅ | `test_busqueda_filtra_por_intervalo_de_fechas` |
| 3 | Sin resultados confiables → lista vacía + aviso | ✅ | `test_busqueda_sin_resultados_confiables_devuelve_lista_vacia`; verificado con `curl` real: "recetas de cocina italiana" → `{"resultados": [], "total": 0}` |
| 4 | Pulgar arriba/abajo asociado a consulta y fragmento | ✅ | `tests/api/test_feedback.py` (4 tests); verificado con `curl -X POST /valorar` real vía la interfaz web |
| 5 | Ingesta produce ≥1 fragmento con embedding | ✅ | `tests/api/test_ingest.py::test_ingerir_boletin_crea_fragmentos_con_embeddings` |
| 6 | `docker compose up --build` levanta todo con datos de ejemplo, en macOS y Windows | ⚠️ parcial | Verificado en macOS (esta máquina): `docker compose up -d --build --wait` deja `db`/`backend`/`web` healthy, con seed cargado y búsqueda funcionando. **No se probó en Windows** (no había una máquina Windows disponible en esta sesión); el diseño no usa nada específico de plataforma (todo corre dentro de contenedores Linux vía Docker Desktop), pero la verificación real en Windows queda pendiente. |

## Success Criteria (spec.md sección 12, MVP)

| Criterio | Estado | Evidencia |
|---|---|---|
| SC-001: ≥95% de registros únicos | ✅ | Idempotencia verificada por identificador y por hash de contenido (`test_ingerir_boletin_es_idempotente_por_*`); un boletín repetido nunca duplica |
| SC-002: 100% de resultados con fecha y URL | ✅ | Garantizado por esquema (`NOT NULL` en `fecha_publicacion`/`url_oficial`) y por la forma de la respuesta de `/v1/search` |
| SC-003: filtro de fecha funciona en todos los resultados | ✅ | Ver escenario 2 |
| SC-004: respuesta &lt;2s para búsquedas comunes | ⚠️ no medido formalmente | Las búsquedas manuales contra el corpus de 6 boletines de ejemplo respondieron en bien menos de 1s, pero no hay un test de performance automatizado que lo verifique con un corpus representativo. Queda como gap conocido; no había una tarea dedicada a esto en `tasks.md`. |
| SC-005: ≥80% evaluación manual positiva | ⏳ pendiente | Requiere consultas representativas contra datos reales; el corpus actual es de ejemplo/ficticio (ver pregunta abierta 1 del design spec sobre el feed real). No se puede evaluar todavía de forma significativa. |
| SC-006: entorno Docker arranca sano en macOS y Windows | ⚠️ parcial | Igual que el escenario 6: verificado en macOS, Windows pendiente |

## Otras verificaciones reales hechas durante `implement`

- **36 tests automatizados en verde** (`pytest -m "not docker"`, incluye el test real contra el modelo `Qwen/Qwen3-Embedding-0.6B`, que efectivamente descarga y genera vectores de 1024 dimensiones).
- **1 smoke test de Docker en verde** (`pytest -m docker`): build de las dos imágenes, los tres servicios healthy, búsqueda real funcionando, `docker compose down` limpia todo.
- **CI en GitHub Actions corrida de verdad** tras el push (no solo el YAML escrito): ver run en el repositorio, job `test` (pytest + modelo real) y job `smoke` (docker compose real).
- **Migraciones**: `alembic upgrade head` → `alembic check` (sin drift) → `alembic downgrade base` → `alembic upgrade head`, ciclo completo verificado dos veces.
- **Bug real encontrado y corregido durante la verificación**: imagen del backend en 9.68 GB por resolver `torch` con CUDA; bajó a 1.97 GB fijando el índice CPU-only de PyTorch.
- **Bug real encontrado y corregido**: `DATABASE_URL` exportada en el shell del desarrollador se filtraba a `docker compose up`, pisando la URL interna (`db:5432`) del `.env` y haciendo fallar el arranque del backend. El smoke test ahora corre con un entorno sin esa variable.
- **Gap real encontrado y corregido**: el Dockerfile del backend no corría las migraciones al arrancar; se agregó `entrypoint.sh` con `alembic upgrade head` antes de `uvicorn`.
- **Bug real encontrado en la primera corrida de CI en GitHub Actions**: el job `smoke` fallaba porque nunca corría `cp .env.example .env` (ese archivo está en `.gitignore` y no llega al runner). Sin él, `docker-compose.yml` no tenía valores para ninguna variable sin default explícito, y el volumen `model-cache:${EMBEDDING_CACHE_DIR}` se volvía inválido (`model-cache:`, ruta vacía). Se agregó el paso al workflow. Esto pasó inadvertido en las corridas locales porque el `.env` ya existía en la máquina de desarrollo desde el bloque de Setup.
- **Inconsistencia real encontrada y corregida en el spec de diseño**: REQ-05 exigía `fecha_publicacion` en `fragmentos`, pero la sección 7 no la listaba. Se corrigió el spec (v0.5) y el esquema real coincide.

## Hallazgos de uso manual (post-verify)

Encontrados usando el MVP ya verificado, con el corpus de 6 boletines de ejemplo. Son evidencia directa de por qué SC-005 (evaluación manual con datos reales) sigue pendiente: un corpus tan chico hace visibles tanto falsos negativos como falsos positivos que un corpus real diluiría.

1. **"salud" no encontraba los 2 boletines que la contienen literalmente** (similitud 0.41-0.45, por debajo del umbral 0.5 de REQ-15). **Resuelto**: se agregaron los modos HYBRID/ALL (REQ-26 a REQ-29, v0.6 del design spec) — una coincidencia de texto exacto rescata el resultado en HYBRID. Verificado con `curl` real contra los 3 modos.
2. **Consulta compuesta "calendarios propuestos por el ministerio de salud" devuelve `BO-DEMO-0004`** (calendario escolar, nada que ver con salud) con similitud 0.5017, apenas sobre el umbral. **Sin resolver, documentado a propósito**: no es un bug de código — `coincidencia_texto=False` en los 3 modos, confirma que es el vector puro. La búsqueda semántica mide similitud global entre consulta y texto, no exige que todos los conceptos de una consulta compuesta coincidan a la vez; con solo 6 documentos, un match parcial en "calendario" alcanza para superar el umbral. Es muy probable que sea mucho menos frecuente con un corpus real más grande. Decisión: no tocar el umbral ni agregar lógica de "AND" entre conceptos todavía, esperar a tener datos reales para calibrar con evidencia real en vez de reaccionar a un caso de un corpus de 6 documentos ficticios.

## Gaps conocidos, sin resolver

1. **Windows no probado de verdad** (escenario 6 / SC-006): el diseño no depende de nada específico del SO host, pero falta la verificación real.
2. **SC-004 (tiempo de respuesta) sin medición automatizada**: no hay un test de carga/performance en la suite.
3. **SC-005 (evaluación manual)**: no se puede evaluar de forma significativa hasta tener datos reales del feed de boletines (pregunta abierta 1 del design spec). Los dos hallazgos de la sección anterior son evidencia concreta de esto.

Estos gaps no bloquean el avance de fase (el gate `implement → verify` no pide artefactos ni checks), pero quedan documentados para no perderlos de vista antes de dar el MVP por cerrado.
