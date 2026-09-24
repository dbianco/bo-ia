# Plan: Etapa 4 — Notificaciones

Framework: spec-kit (track default)
Feature ID: f_01m39nchns3qv6gpdzp34pg4pm
Fuente: `spec.md` de esta feature

## Technical Context

- **Lenguaje y versión:** Python 3.12, mismo backend consolidado.
- **Dependencias nuevas:** ninguna. El envío de correo usa `smtplib`/`email.message.EmailMessage` de la librería estándar, configurado por variables de entorno (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`).
- **Almacenamiento:** 1 tabla nueva — `entregas_notificacion`, con `UniqueConstraint(match_id, canal)` (FR-003) y `CheckConstraint` sobre `canal` y `estado`.
- **Herramientas de testing:** pytest; `unittest.mock.patch` sobre `smtplib.SMTP` para los tests de envío (decisión ya tomada en `spec.md`: sin Mailhog en `docker-compose.yml`).
- **Plataforma objetivo:** sin cambios.
- **Objetivos de performance y restricciones:** el despacho de entregas es síncrono, disparado desde `evaluar_documento` justo después de crear cada `EvaluacionMatch` nuevo — mismo criterio de volumen chico que ya justificó la evaluación síncrona en la Etapa 3.

## Constitution Check

- **Sin datos personales en logs:** el cuerpo del correo y el email destinatario no se loguean; un error de SMTP se guarda en `error_proveedor` (mensaje de la excepción, sin credenciales — `smtplib` no las incluye en sus mensajes de error estándar).
- **Timeout y retry en llamadas HTTP salientes:** la conexión SMTP usa un timeout explícito (FR-009); no hay retry automático en esta etapa (decisión ya tomada en `spec.md` — desviación consciente del texto original de la sección 8, documentada como gap).
- **Migraciones de esquema reversibles con rollback probado:** una revisión Alembic nueva crea `entregas_notificacion`, con `downgrade` completo, probada con el mismo patrón `upgrade → downgrade → upgrade`.
- **Cambios de API pública aditivos:** `GET /v1/notificaciones` es nuevo; `POST /v1/suscripciones` gana un campo opcional `canales` (con default `[]`, retrocompatible) — no rompe ningún test existente de la Etapa 3.
- **Secretos desde el entorno:** las credenciales SMTP vienen de variables de entorno (`SMTP_USER`, `SMTP_PASSWORD`), documentadas en `.env.example`, nunca en código.
- **Tests en CI antes de mergear:** se agregan al mismo `ci.yml`, sin markers nuevos (todo mockeado, no hay llamada de red real).
- **Accesibilidad:** no aplica; esta etapa no agrega pantallas a la interfaz web.

## Project Structure

Lista inicial; se actualiza con el nombre real de la migración y el árbol final antes de `verify`.

Modificados:

- `backend/src/db/models.py`
- `backend/src/subscriptions/evaluator.py` (llama a `crear_entregas_para_match` tras crear cada match nuevo)
- `backend/src/api/suscripciones.py` (acepta `canales` al crear una suscripción, valida contra el conjunto fijo)
- `backend/src/api/main.py` (registra el router de notificaciones)
- `.env.example` (variables `SMTP_*`)
- `README.md`
- `backend/tests/test_migrations.py`

Nuevos:

- `backend/src/db/migrations/versions/<rev>_create_entregas_notificacion.py`
- `backend/src/notifications/__init__.py`
- `backend/src/notifications/email.py` (`enviar_correo`, `EnvioCorreoFallido`)
- `backend/src/notifications/dispatcher.py` (`crear_entregas_para_match`)
- `backend/src/api/notificaciones.py` (`GET /v1/notificaciones`)
- `backend/tests/notifications/test_email.py`
- `backend/tests/notifications/test_dispatcher.py`
- `backend/tests/api/test_notificaciones.py`
- `backend/tests/api/test_suscripciones.py` (se extiende: `canales` al crear)

## Research

- **`smtplib`/`email` de la librería estándar, no una API transaccional de terceros:** evita una dependencia nueva y una cuenta de proveedor externo para esta primera versión; cualquier SMTP relay (incluido uno propio) sirve. Coherente con el criterio ya usado para el hash de contraseña en la Etapa 3.
- **Sin Mailhog en `docker-compose.yml`:** decisión ya tomada en `spec.md`. Los tests mockean `smtplib.SMTP`; no hay forma de ver un correo "real" en desarrollo local sin credenciales SMTP propias del usuario.
- **Sin reintento automático:** decisión ya tomada en `spec.md`, desviación consciente del alcance original de la sección 8 (que sí mencionaba "reintentos"). El campo `reintentos` queda en el modelo para un reintento manual futuro, sin lógica que lo incremente todavía.
- **`crear_entregas_para_match` se llama directamente desde `evaluar_documento`, no vía callback:** mismo patrón ya decidido en la Etapa 3 para `evaluar_documento` desde `ingerir_documento` — la sección 6.3 del design spec dibuja "genera una entrega pendiente" como parte del mismo flujo de evaluación, no como un paso opcional. Se llama después de `session.flush()` del match (para tener su `id`) y antes del `session.commit()` de `evaluar_documento`.
- **Falla de correo atrapada en dos niveles:** `enviar_correo` convierte `OSError`/`smtplib.SMTPException` (conexión rechazada, timeout, auth fallida, DNS) en `EnvioCorreoFallido`; `_intentar_entrega` además atrapa cualquier `Exception` no prevista alrededor del intento de correo, como red de seguridad adicional para que FR-007 valga incluso ante un bug propio, no solo ante una falla de SMTP esperada.
- **`canales` se valida en `POST /v1/suscripciones`, no en `construir_filtros_suscripcion`:** son conceptos distintos (filtros de metadata vs. canales de notificación); reutilizar el módulo de filtros para esto sería forzado. La validación vive junto al endpoint, contra el conjunto fijo `{"bandeja", "correo"}`.
