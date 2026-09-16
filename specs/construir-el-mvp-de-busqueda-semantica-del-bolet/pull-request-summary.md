# Pull request — MVP público de búsqueda semántica del Boletín Oficial

Feature ID: `f_01m2npz2d7t6489bgwchqas3wm` · Framework: spec-kit

Nota: este proyecto trabajó directo sobre `main` durante toda la implementación (sin rama separada por feature), así que este documento cumple el rol del resumen de PR que pide la fase `integrate`, sin un pull request real de GitHub que mergear.

## Historia de usuario

Como usuario público, quiero buscar boletines oficiales de la Provincia de Córdoba mediante una consulta en lenguaje natural, acotable por fecha, para encontrar información relevante sin revisar boletines uno por uno, verificando cada resultado en la fuente oficial.

## Requisitos funcionales implementados

FR-001 a FR-017 (`spec.md`, Etapa 1 completa) más el follow-on de búsqueda híbrida, agregado directamente al design spec como REQ-26 a REQ-31 (`docs/superpowers/specs/2026-09-16-boletin-oficial-design.md`, v0.6): modos de búsqueda SEMANTIC/HYBRID/ALL, búsqueda de texto completo en español, fusión de rankings por RRF.

## Resumen de evidencia

- 46 tests en verde (45 rápidos vía `pytest -m "not docker"`, incluido el modelo real de embeddings, + 1 smoke test de Docker), lint (`ruff`) en 0, CI en GitHub Actions corrida real y verde.
- Seguridad: `pip-audit` encontró 10 vulnerabilidades reales; `pytest` corregido (8.4.2 → 9.1.1), `transformers` con riesgo aceptado y documentado (ninguna ruta vulnerable usada por la app). Detalle completo en `verify-evidence.md`.
- 4 bugs reales y 1 inconsistencia de spec encontrados y corregidos durante la verificación (imagen Docker con CUDA de sobra, fuga de `DATABASE_URL` del shell a `docker compose`, migraciones que no corrían al arrancar, CI sin `.env`, `fecha_publicacion` faltante en el modelo de `fragmentos`).
- 2 hallazgos reales de uso manual post-verify: "salud" no encontraba resultados con match literal (resuelto con HYBRID/ALL) y un falso positivo parcial en consultas compuestas (documentado, sin resolver a propósito — depende de datos reales).

## Enlaces

- `specs/construir-el-mvp-de-busqueda-semantica-del-bolet/spec.md`
- `specs/construir-el-mvp-de-busqueda-semantica-del-bolet/plan.md`
- `specs/construir-el-mvp-de-busqueda-semantica-del-bolet/tasks.md`
- `specs/construir-el-mvp-de-busqueda-semantica-del-bolet/verify-evidence.md`
- `docs/superpowers/specs/2026-09-16-boletin-oficial-design.md`
- CI: https://github.com/dbianco/bo-ia/actions/workflows/ci.yml

## Estado de merge

Ya integrado a `main` (commits `caa2538`..`5f1ffa1`). No requiere un merge adicional.
