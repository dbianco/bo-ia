# Pull request — Etapa 3: clientes y suscripciones

Feature ID: `f_01m37xd2yt0zvrz0rkbb46x6qz` · Framework: spec-kit

Nota: igual que las etapas anteriores, este trabajo se hizo directo sobre `main` (sin rama separada), así que este documento cumple el rol del resumen de PR que pide la fase `integrate`, sin un pull request real de GitHub que mergear.

## Historia de usuario

Como cliente de una instalación, quiero crear una cuenta y suscribirme a una consulta de mi interés, para que el sistema me marque automáticamente los documentos nuevos que la matchean, sin tener que repetir la búsqueda a mano.

## Requisitos funcionales implementados

FR-001 a FR-017 (`spec.md`, Etapa 3 completa): autenticación con sesiones respaldadas por tabla (registro, login, logout), suscripciones con propiedad por usuario y filtros validados/snapshoteados contra `installation.yaml`, y evaluación síncrona de documentos nuevos contra suscripciones activas al completar `ingerir_documento`, con evidencia (`EvaluacionMatch`: score, filtros aplicados, fecha).

## Resumen de evidencia

- 114 tests automatizados en verde (`pytest --ignore=tests/smoke -m "not live"`), lint (`ruff`) en 0, smoke Docker real en verde.
- Verificado en real contra el stack levantado: registro, login (cookie seteada), creación de suscripción, listado propio, 401 sin sesión — y una ingesta real (`POST /v1/documentos`) que produjo un `EvaluacionMatch` real (score 0.7896) con el modelo de embeddings real, confirmado consultando Postgres directamente.
- `GET /v1/search` y `GET /v1/config` siguen públicos y sin cambios: toda la suite de búsqueda de las Etapas 1 y 2 pasa sin modificar un solo archivo de esos tests.
- 2 bugs reales encontrados y corregidos: `conftest.py` no truncaba `usuarios` (filtraba datos entre tests); `evaluar_documento` se llamaba originalmente dentro del `try/except` de fragmentación de `ingerir_documento`, lo que hubiera podido marcar como `estado="error"` un documento ya ingerido correctamente si la evaluación fallaba. Detalle completo en `verify-evidence.md`.
- Sin dependencias nuevas: hash de contraseña con `hashlib.pbkdf2_hmac` y token de sesión con `secrets.token_urlsafe`, ambos de la librería estándar.

## Enlaces

- `specs/etapa-3-clientes-suscripciones/spec.md`
- `specs/etapa-3-clientes-suscripciones/plan.md`
- `specs/etapa-3-clientes-suscripciones/tasks.md`
- `specs/etapa-3-clientes-suscripciones/verify-evidence.md`
- `docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md`

## Estado de merge

Ya integrado a `main` (commits `7b89293`..`421ac91`). No requiere un merge adicional. Falta hacer `git push` al remoto — no se hizo en esta sesión porque no se pidió explícitamente.
