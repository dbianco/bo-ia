# Pull request — Etapa 1: núcleo genérico (Documento)

Feature ID: `f_01m37e47q8s40qfzv53n5bpa1y` · Framework: spec-kit

Nota: igual que la feature del MVP, este trabajo se hizo directo sobre `main` (sin rama separada), así que este documento cumple el rol del resumen de PR que pide la fase `integrate`, sin un pull request real de GitHub que mergear.

## Historia de usuario

Como desarrollador de la plataforma, quiero que el núcleo de ingesta y búsqueda sea genérico (`Documento`, no `Boletin`) y configurable por instalación, para poder incorporar una segunda fuente temática sin duplicar el motor.

## Requisitos funcionales implementados

FR-001 a FR-017 (`spec.md`, Etapa 1 completa): tabla `documentos` genérica, tabla `fuentes`, `metadata` JSONB con índice GIN, contrato único de ingesta (`ingerir_documento`), `installation.yaml` con filtros declarados (`seleccion`, `rango_numerico`), `aplicar_filtros` reutilizable, `GET /v1/config`, `filtro.<clave>` en `GET /v1/search`, migración única y reversible con backfill.

## Resumen de evidencia

- 65 tests en verde (`pytest --ignore=tests/smoke`, incluye el modelo real de embeddings) + 1 smoke test de Docker real (`docker compose up --build` reconstruyendo sobre la base de datos de desarrollo existente). Lint (`ruff`) en 0.
- 2 bugs reales encontrados y corregidos: doble-encoding en el filtro JSONB (`cast(json.dumps(...), JSONB)` → `literal(valor, type_=JSONB)`), y un test propio mal diseñado que confundía idempotencia por hash con colisión entre fuentes.
- Riesgo 10.6 del design spec (índice HNSW + filtro selectivo) investigado: `hnsw.iterative_scan` confirmado apagado por defecto en la instancia real (pgvector 0.8.5); no se logró reproducir una pérdida de recall con datos sintéticos. Documentado como gap abierto para cuando haya un corpus real de mayor volumen. Detalle completo en `verify-evidence.md`.
- Desviación consciente de la constitución de la compañía (cambios de API aditivos): `POST /v1/boletines` se renombra a `POST /v1/documentos` sin capa de compatibilidad, porque la API no tiene consumidores externos todavía. Registrado en `plan.md` → Constitution Check.

## Enlaces

- `specs/etapa-1-nucleo-generico-documento/spec.md`
- `specs/etapa-1-nucleo-generico-documento/plan.md`
- `specs/etapa-1-nucleo-generico-documento/tasks.md`
- `specs/etapa-1-nucleo-generico-documento/verify-evidence.md`
- `docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md`
- `installation.yaml`

## Estado de merge

Ya integrado a `main` (commits `196bbca`..`3d8b774`). No requiere un merge adicional. Falta hacer `git push` al remoto — no se hizo en esta sesión porque no se pidió explícitamente.
