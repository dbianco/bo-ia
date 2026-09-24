# Pull request — Etapa 4: notificaciones

Feature ID: `f_01m39nchns3qv6gpdzp34pg4pm` · Framework: spec-kit

Nota: igual que las etapas anteriores, este trabajo se hizo directo sobre `main` (sin rama separada), así que este documento cumple el rol del resumen de PR que pide la fase `integrate`, sin un pull request real de GitHub que mergear.

## Historia de usuario

Como cliente con una suscripción activa, quiero enterarme de los documentos nuevos que la matchean sin tener que revisar la plataforma a diario, para no perderme algo relevante.

## Requisitos funcionales implementados

FR-001 a FR-010 (`spec.md`, Etapa 4 completa): registro de una `EntregaNotificacion` por cada canal declarado en una suscripción al crearse un `EvaluacionMatch` (con `"bandeja"` como default), sin duplicados por (match, canal); entrega "bandeja" marcada `entregada` de inmediato, sin llamada externa; entrega "correo" con intento real de envío por SMTP (stdlib `smtplib`/`email`, configurado enteramente por variables de entorno, con timeout explícito), que falla de forma controlada (`estado="fallida"`, `error_proveedor` poblado) sin interrumpir la ingesta ni el resto de la evaluación cuando SMTP no está configurado o el envío falla; `GET /v1/notificaciones` como bandeja de avisos propia, sin ver las de otros usuarios; validación de `canales` contra el conjunto fijo `{"bandeja", "correo"}` al crear una suscripción, con 422 ante un canal no declarado.

## Resumen de evidencia

- 128/128 tests automatizados en verde (`pytest -m "not slow and not docker and not live"`), lint (`ruff`) en 0, smoke Docker real en verde (`pytest -m docker`).
- Verificado en real contra el stack levantado, con `SMTP_HOST` intencionalmente vacío para probar la falla controlada de verdad (no solo mockeada): registro, login, creación de una suscripción con `canales: ["bandeja", "correo"]`, ingesta real de un documento nuevo que matcheó (modelo de embeddings real) → `estado: "completo"` (la ingesta no se interrumpió pese al fallo de correo). `GET /v1/notificaciones` devolvió las 2 entregas esperadas: `bandeja` → `entregada`, `correo` → `fallida` con `error_proveedor = "SMTP_HOST no está configurado"`, confirmado también consultando Postgres directamente.
- `GET /v1/search`, `GET /v1/config` y toda la suite de suscripciones/auth de las Etapas 1-3 siguen en verde sin modificar sus archivos de test (salvo la extensión esperada de `test_suscripciones.py` para `canales`).
- 2 bugs reales encontrados y corregidos durante `implement`: faltaba la relación `documento` en `EvaluacionMatch` (necesaria para armar el cuerpo del correo); un import sin uso detectado por `ruff` tras cambiar de fixture de embeddings en un test. Detalle completo en `verify-evidence.md`.
- Sin dependencias nuevas: envío de correo con `smtplib`/`email` de la librería estándar, mismo criterio que el hash de contraseña de la Etapa 3.
- 2 decisiones de alcance explícitas, documentadas como gaps: sin reintento automático de entregas fallidas (desviación consciente del alcance original de la sección 8); sin contenedor Mailhog en `docker-compose.yml` (los tests mockean `smtplib.SMTP`).

## Enlaces

- `specs/etapa-4-notificaciones/spec.md`
- `specs/etapa-4-notificaciones/plan.md`
- `specs/etapa-4-notificaciones/tasks.md`
- `specs/etapa-4-notificaciones/verify-evidence.md`
- `docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md`

## Estado de merge

Ya integrado a `main` (commits `30e0b82`..`131b48a`). No requiere un merge adicional. Falta hacer `git push` al remoto — no se hizo en esta sesión porque no se pidió explícitamente.
