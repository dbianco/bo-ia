# Evidencia de verificación — Etapa 1 (núcleo genérico Documento)

Feature ID: `f_01m37e47q8s40qfzv53n5bpa1y` · Fecha: 2026-09-23

Cruza cada escenario de aceptación y criterio de éxito de `spec.md` contra la verificación real hecha durante `implement`. Todo lo marcado ✅ se corrió con comandos reales: `pytest` contra Postgres real (puerto 9100), `alembic upgrade/downgrade` real, y `docker compose up --build` real (smoke test), no simulado.

## Acceptance scenarios (spec.md)

| # | Escenario | Estado | Evidencia |
|---|---|---|---|
| 1 | El núcleo no menciona `Boletin` salvo en el adaptador/seed/config | ✅ | `grep -ril boletin backend/src/db backend/src/api backend/src/ingestor` (excluyendo `ingestor/adapters/boletin.py` y las migraciones viejas) → 0 matches |
| 2 | Dos fuentes conviven sin colisión de identificador | ✅ | `tests/ingestor/test_ingestor.py::test_dos_fuentes_distintas_no_colisionan_con_el_mismo_identificador`; `tests/api/test_search_filters.py::test_dos_fuentes_conviven_en_busqueda_sin_filtro` |
| 3 | `GET /v1/config` expone los filtros declarados | ✅ | `tests/api/test_config.py` |
| 4 | Filtrar por `municipio=Carlos Paz` excluye `Noetinger` | ✅ | `tests/api/test_search_filters.py::test_filtro_municipio_carlos_paz_excluye_noetinger` |
| 5 | Clave de filtro no declarada → 422 sin ejecutar la consulta | ✅ | `tests/search/test_filters.py::test_filtro_no_declarado_es_rechazado`; `tests/api/test_search_filters.py::test_filtro_no_declarado_devuelve_422` |
| 6 | Suite del MVP sigue en verde tras la migración y el renombre | ✅ | 65/65 tests no-Docker en verde (ver más abajo); smoke Docker en verde |
| 7 | Migración: `upgrade → downgrade → upgrade` sin pérdida de datos | ✅ | `tests/test_migrations.py` (3 tests, incluye backfill con datos reales) |

## Success Criteria (spec.md)

| Criterio | Estado | Evidencia |
|---|---|---|
| SC-001: 0 referencias a `boletin` en el núcleo | ✅ | Ver escenario 1 |
| SC-002: documentos de 2 fuentes distintas, ambos presentes en búsqueda sin filtro | ✅ | `test_dos_fuentes_conviven_en_busqueda_sin_filtro` |
| SC-003: renombrar/agregar un filtro declarado no toca `backend/src/` | ✅ | El filtro `presupuesto_estimado` (tipo `rango_numerico`) se probó en `tests/search/test_filters.py` sin tocar el motor; agregarlo a `installation.yaml` alcanza |
| SC-004: 100% de la suite del MVP pasa tras el renombre | ✅ | 65/65 (ver detalle abajo) |
| SC-005: filtro `municipio=Carlos Paz` → 0 resultados `Noetinger` | ✅ | Ver escenario 4 |
| SC-006: ciclo `upgrade → downgrade → upgrade` sin errores ni pérdida de datos | ✅ | `tests/test_migrations.py`, corrido 2 veces (aislado y dentro de la suite completa) |

## Trazabilidad FR → test

| FR | Cubierto por |
|---|---|
| FR-001, FR-004, FR-005 | `backend/src/db/models.py` (esquema); `tests/test_migrations.py` |
| FR-002, FR-003, FR-006 | `tests/ingestor/test_ingestor.py` |
| FR-007, FR-008 | `tests/config/test_installation.py` |
| FR-009, FR-012, FR-013 | `tests/search/test_filters.py` |
| FR-010 | `tests/api/test_config.py` |
| FR-011 | `tests/api/test_search_filters.py` |
| FR-014, FR-015 | `tests/test_migrations.py` |
| FR-016 | `tests/api/test_ingest.py`, `tests/api/test_search.py`, `tests/api/test_search_hybrid.py`, `tests/api/test_feedback.py`, `tests/smoke/test_docker_up.py` (real) |
| FR-017 | Ver escenario 1 (SC-001) |

## Riesgo 10.6 del design spec (índice HNSW + filtro selectivo)

- **Confirmado contra la instancia real** (`pgvector` 0.8.5, imagen `pgvector/pgvector:pg16`): `hnsw.iterative_scan` (la mitigación de pgvector) está **apagado por defecto**. `tests/api/test_search_recall.py::test_hnsw_iterative_scan_esta_apagado_por_defecto`.
- **No se pudo reproducir una pérdida real de recall** con datos sintéticos, ni con 200 fragmentos "ruido" bajo la configuración por defecto (`tests/api/test_search_recall.py::test_filtro_selectivo_encuentra_el_unico_match_con_muchos_no_matches`), ni forzando `hnsw.ef_search = 1` sin `iterative_scan` con hasta 500 fragmentos adversariales (vectores casi ortogonales). El caso sintético no estresa el índice de la misma forma que embeddings reales de alta dimensión.
- **Gap conocido, sin resolver**: el riesgo sigue siendo real en teoría (documentado por pgvector) pero no verificado con un corpus real de volumen. Queda para la Etapa 2, cuando haya un corpus real más grande: si aparece evidencia de recall degradado, activar `hnsw.iterative_scan = relaxed_order` (probado en un experimento manual: con `ef_search=1` y `enable_seqscan=off`, recuperó el match que un ajuste de `ef_search` insuficiente podía perder).

## Checklist de la fase `verify`

- **Lint (ruff):** `ruff check src tests` → 3 hallazgos (2 auto-fixeables, 1 orden de imports), corregidos con `--fix`. **Resultado: 0 hallazgos.**
- **Tests:** 65/65 en verde (`pytest --ignore=tests/smoke`, incluye el test real contra el modelo `Qwen/Qwen3-Embedding-0.6B` y los 2 tests marcados `slow` de esta etapa).
- **Smoke Docker real:** `pytest -m docker tests/smoke/test_docker_up.py` → 1/1 en verde. Reconstruyó las imágenes, aplicó la migración de esta etapa sobre la base de datos de desarrollo existente (con datos del MVP), cargó `installation.yaml` (3 fuentes), sembró los documentos de ejemplo con el modelo real, y `GET /v1/search?q=presupuesto+provincial` devolvió resultados reales. `docker compose down` al final, como en cada corrida.
- **files_changed:** ver `plan.md` → Project Structure para el árbol final (21 modificados, 13 nuevos, 2 eliminados).

## Bugs reales encontrados y corregidos durante `implement`

1. **Doble-encoding en el filtro de selección JSONB**: `cast(json.dumps(...), JSONB)` serializaba el dict y Postgres lo serializaba de nuevo al castear, así que `@>` nunca matcheaba (0 resultados en todos los casos). Corregido usando `literal(valor, type_=JSONB)`, cuyo bind processor serializa una sola vez. Encontrado por `tests/search/test_filters.py` fallando con resultado vacío en vez de un error — se investigó comparando la containment query cruda en `psql` contra la compilada por SQLAlchemy antes de encontrar la causa.
2. **Test propio mal diseñado** (no bug de producto): `test_dos_fuentes_distintas_no_colisionan_con_el_mismo_identificador` usaba el mismo `texto` para ambos documentos, así que la idempotencia por hash de contenido (comportamiento heredado del MVP, correcto) los trataba como el mismo documento. Se corrigió el test para usar textos distintos por fuente.

## Gaps conocidos, sin resolver

1. **Riesgo 10.6 (HNSW + filtro selectivo)**: ver sección dedicada arriba — confirmado en teoría, no reproducido con datos sintéticos, pendiente de volumen real.
2. **`rango_numerico` sin ejercitar de punta a punta vía HTTP**: `aplicar_filtros` lo soporta y está probado en `tests/search/test_filters.py`, pero `installation.yaml` de esta instalación solo declara filtros `seleccion` (no hay un campo numérico en el vertical Boletín todavía). Queda para cuando exista un vertical o fuente con datos numéricos reales (p. ej. licitaciones, Etapa 5).
3. **Windows no probado** (heredado del MVP, sin cambios en esta etapa): el smoke Docker se corrió en macOS.
