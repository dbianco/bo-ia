# Feature: Etapa 4 — Notificaciones

Framework: spec-kit (track default)
Feature ID: f_01m39nchns3qv6gpdzp34pg4pm
Fuente: `docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md` (v0.2), sección 4.6 (Notificaciones) y 8 (Etapa 4)

## User Scenarios

### Primary user story

Como cliente con una suscripción activa, quiero enterarme de los documentos nuevos que la matchean sin tener que revisar la plataforma a diario, para no perderme algo relevante.

### Acceptance scenarios

1. **Given** un match nuevo entre un documento y una suscripción activa, **When** la evaluación termina, **Then** queda creada una entrega pendiente por cada canal declarado en la suscripción (o solo "bandeja" si no declaró ninguno).
2. **Given** una entrega por el canal "bandeja", **When** se crea, **Then** queda marcada como entregada de inmediato, sin ninguna acción externa.
3. **Given** una entrega por el canal "correo" con SMTP configurado y funcionando, **When** se crea, **Then** el sistema intenta enviar el correo y, si tiene éxito, la marca como entregada con la fecha del intento.
4. **Given** una entrega por el canal "correo" cuando SMTP no está configurado o el envío falla, **When** se intenta, **Then** queda marcada como fallida con el motivo del error, sin interrumpir la ingesta del documento ni el resto de la evaluación.
5. **Given** un usuario autenticado, **When** consulta su bandeja de avisos, **Then** ve únicamente sus propias entregas, sin las de otros usuarios.
6. **Given** una suscripción, **When** se crea declarando un canal que no es "bandeja" ni "correo", **Then** el sistema la rechaza.
7. **Given** un match ya procesado, **When** por algún motivo se intenta evaluar de nuevo, **Then** no se crea una segunda entrega para el mismo canal.

## Functional Requirements

### Registro de entregas

- **FR-001**: The system MUST store one `EntregaNotificacion` per (match, canal) pair, with `canal`, `estado` (`pendiente`/`entregada`/`fallida`), `fecha_intento`, `reintentos`, `error_proveedor`, and a reference to the `EvaluacionMatch` it belongs to (which already links the document and the subscription).
- **FR-002**: WHEN an `EvaluacionMatch` is created, the system SHALL create one `EntregaNotificacion` per channel declared on the subscription, defaulting to `["bandeja"]` when the subscription declares no channels.
- **FR-003**: A duplicate `EntregaNotificacion` for the same (match, canal) pair MUST NOT be created.

### Canal "bandeja"

- **FR-004**: A "bandeja" delivery MUST be marked `entregada` immediately at creation, with no external call.
- **FR-005**: An authenticated user MUST be able to list their own deliveries via `GET /v1/notificaciones`, ordered from most recent, and MUST NOT see another user's deliveries.

### Canal "correo"

- **FR-006**: The system MUST attempt to send an email for a "correo" delivery at creation time, to the subscription owner's account email, over SMTP configured entirely from environment variables.
- **FR-007**: WHEN SMTP is not configured or the send attempt fails, the system SHALL mark the delivery `fallida`, record the failure reason in `error_proveedor`, and MUST NOT raise an exception that interrupts document ingestion or the rest of the evaluation.
- **FR-008**: A successful send MUST mark the delivery `entregada` and record `fecha_intento`.
- **FR-009**: Every outbound SMTP connection MUST use an explicit timeout.

### Suscripción: canales

- **FR-010**: A user MUST be able to declare which channels a subscription uses when creating it, from the fixed set `{"bandeja", "correo"}`; an undeclared/unknown channel MUST be rejected with HTTP 422.

## Success Criteria

- **SC-001**: A match with both channels declared creates exactly 2 `EntregaNotificacion` rows (1 per channel); a match with no channels declared creates exactly 1 (`bandeja`).
- **SC-002**: Re-running evaluation against an already-processed match creates 0 additional `EntregaNotificacion` rows for a (match, canal) pair that already has one.
- **SC-003**: A "bandeja" delivery is `estado = "entregada"` immediately after creation, with 0 outbound network calls made for it.
- **SC-004**: `GET /v1/notificaciones` returns HTTP 401 without a session; with a session, 100% of the rows returned belong to the caller.
- **SC-005**: A successful SMTP send (verified with a mocked SMTP client) marks the delivery `entregada` with `fecha_intento` set.
- **SC-006**: A failed SMTP send (mocked failure, or missing SMTP configuration) marks the delivery `fallida` with `error_proveedor` populated, and document ingestion still completes successfully — verified with a test where SMTP is intentionally broken.
- **SC-007**: Creating a subscription with an undeclared channel returns HTTP 422 and creates 0 rows.

## Clarifications

- **Q**: ¿Cómo se prueba el envío de correo en desarrollo local? **A**: Con mocks de `smtplib` en los tests. No se agrega un contenedor de captura de correo (Mailhog) a `docker-compose.yml` en esta etapa; sin credenciales SMTP reales, no hay forma de ver un correo "enviado" de verdad en desarrollo local. (2026-09-24)
- **Q**: ¿Cómo se reintenta una entrega de correo que falla? **A**: No hay reintento automático en esta etapa. Una entrega fallida queda registrada con su error; el campo `reintentos` arranca en 0 y queda preparado para un reintento futuro, pero no existe todavía un endpoint ni un job que lo dispare. "Reintentos automáticos" queda como gap explícito para una etapa futura, aunque el alcance original de la sección 8 los mencionaba. (2026-09-24)
- **Q**: ¿Qué pasa si SMTP no está configurado? **A**: El canal "correo" falla de forma controlada (`estado = "fallida"`, con el motivo en `error_proveedor`) sin interrumpir la ingesta del documento. Una instalación sin SMTP configurado puede seguir usando "bandeja" igual. (2026-09-24)
- **Q**: ¿Qué biblioteca se usa para enviar el correo? **A**: `smtplib`/`email` de la librería estándar, sin sumar una dependencia nueva, configurado con variables de entorno (host, puerto, usuario, contraseña, remitente) — resuelto en `plan.md`. (2026-09-24)
