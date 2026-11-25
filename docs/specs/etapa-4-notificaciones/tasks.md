# Tasks: Etapa 4 — Notificaciones

Framework: spec-kit (track default)
Feature ID: f_01m39nchns3qv6gpdzp34pg4pm
Fuente: `plan.md` de esta feature (Project Structure y Research)

Orden: toda dependencia aparece antes que la tarea que depende de ella. `[P]` marca tareas que pueden hacerse en paralelo (no dependen entre sí y tocan archivos distintos).

## Tasks

### Modelo de datos y migración

- [x] T001 Agregar el modelo `EntregaNotificacion` (tabla `entregas_notificacion`: `match_id`, `canal`, `estado`, `fecha_intento`, `reintentos`, `error_proveedor`) en `backend/src/db/models.py` (FR-001)
- [x] T002 Escribir la migración Alembic que crea `entregas_notificacion`, con `UniqueConstraint(match_id, canal)` y `downgrade` completo, en `backend/src/db/migrations/versions/`, depends on T001
- [x] T003 Extender el ciclo `upgrade → downgrade → upgrade` de `backend/tests/test_migrations.py` para la nueva revisión, depends on T002

### Envío de correo (TDD)

- [x] T004 [P] Escribir tests que fallen para `enviar_correo` (éxito con SMTP mockeado, `EnvioCorreoFallido` si falta `SMTP_HOST`, `EnvioCorreoFallido` si `smtplib` lanza una excepción) en `backend/tests/notifications/test_email.py` (FR-006, FR-007, FR-009), depends on T002
- [x] T005 Implementar `enviar_correo`/`EnvioCorreoFallido` con `smtplib`/`email` en `backend/src/notifications/email.py`, depends on T004

### Dispatcher de entregas (TDD)

- [x] T006 [P] Escribir tests que fallen para `crear_entregas_para_match`: 1 entrega "bandeja" por defecto (SC-001), 2 si la suscripción declara ambos canales, "bandeja" queda `entregada` sin llamar a SMTP (SC-003), "correo" exitoso/fallido con SMTP mockeado (SC-005, SC-006), un correo fallido no propaga la excepción, re-crear entregas para el mismo match no duplica (SC-002), en `backend/tests/notifications/test_dispatcher.py`, depends on T005
- [x] T007 Implementar `crear_entregas_para_match` en `backend/src/notifications/dispatcher.py` (FR-001 a FR-004, FR-007, FR-008), depends on T006

### Enganche con la evaluación

- [x] T008 Llamar a `crear_entregas_para_match` desde `evaluar_documento` justo después de crear cada `EvaluacionMatch` nuevo, en `backend/src/subscriptions/evaluator.py`, depends on T007

### Suscripción: canales

- [x] T009 [P] Escribir tests que fallen para crear una suscripción con `canales` válidos y con un canal no declarado (422) en `backend/tests/api/test_suscripciones.py` (FR-010, SC-007), depends on T002
- [x] T010 Extender `SuscripcionEntrada`/`crear_suscripcion` para aceptar y validar `canales` contra `{"bandeja", "correo"}`, en `backend/src/api/suscripciones.py`, depends on T009

### Bandeja interna (API)

- [x] T011 [P] Escribir tests que fallen para `GET /v1/notificaciones` (lista las propias, 401 sin sesión, no ve las de otro usuario) en `backend/tests/api/test_notificaciones.py` (FR-005, SC-004), depends on T008
- [x] T012 Implementar el router en `backend/src/api/notificaciones.py`, depends on T011
- [x] T013 Registrar el router en `backend/src/api/main.py`, depends on T012

### Configuración

- [x] T014 [P] Documentar `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` en `.env.example`, depends on T005

### Regresión y verificación

- [x] T015 Confirmar que la suite existente de las Etapas 1 a 3 sigue pasando sin cambios, depends on T008, depends on T010, depends on T013
- [x] T016 [P] Actualizar `README.md` con el endpoint de notificaciones, los canales y las variables `SMTP_*`, depends on T013
- [x] T017 Correr la suite completa (migración, correo, dispatcher, canales, bandeja, regresión) y confirmar cada escenario de aceptación y criterio de éxito de `spec.md`; registrar los resultados como evidencia para la fase `verify`, depends on T003, depends on T014, depends on T015, depends on T016
