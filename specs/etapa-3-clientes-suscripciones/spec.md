# Feature: Etapa 3 — Clientes y suscripciones

Framework: spec-kit (track default)
Feature ID: f_01m37xd2yt0zvrz0rkbb46x6qz
Fuente: `docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md` (v0.2), sección 3.2 (Múltiples clientes), 4.5 (Suscripciones), 6.3 (Flujo de suscripción) y 8 (Etapa 3)

## User Scenarios

### Primary user story

Como cliente de una instalación, quiero crear una cuenta y suscribirme a una consulta de mi interés, para que el sistema me marque automáticamente los documentos nuevos que la matchean, sin tener que repetir la búsqueda a mano.

### Acceptance scenarios

1. **Given** un email no registrado, **When** una persona se registra con email y contraseña, **Then** queda creada su cuenta y puede iniciar sesión.
2. **Given** una cuenta existente, **When** inicia sesión con las credenciales correctas, **Then** el sistema crea una sesión y la persona queda autenticada en las siguientes requests (vía cookie).
3. **Given** una sesión activa, **When** la persona cierra sesión, **Then** esa sesión deja de ser válida para requests posteriores.
4. **Given** una persona autenticada, **When** crea una suscripción con un texto de búsqueda y filtros, **Then** queda guardada como propia, con su embedding calculado y en estado activa.
5. **Given** una suscripción propia, **When** su dueño la pausa, la reanuda o la borra, **Then** el cambio se aplica; si otra persona intenta la misma operación sobre una suscripción que no es suya, el sistema lo rechaza.
6. **Given** una suscripción activa cuyo texto matchea semánticamente un documento, **When** ese documento termina de ingerirse, **Then** queda registrado un match con su score, los filtros aplicados y la fecha de evaluación.
7. **Given** una suscripción activa cuyos filtros no matchean la metadata de un documento nuevo, **When** ese documento se ingiere, **Then** no se registra ningún match para esa suscripción, aunque el texto sea semánticamente similar.
8. **Given** una suscripción pausada, **When** se ingiere un documento que matchearía si estuviera activa, **Then** no se evalúa y no se registra ningún match.
9. **Given** `GET /v1/search` y `GET /v1/config`, **When** se llaman sin sesión, **Then** siguen respondiendo igual que en las Etapas 1 y 2 — sin requerir cuenta.

## Functional Requirements

### Autenticación

- **FR-001**: The system MUST allow registering an account with an email and a password; the email MUST be unique across accounts.
- **FR-002**: Passwords MUST be stored as a salted hash, never in plain text, and MUST NOT appear in logs or error messages.
- **FR-003**: The system MUST allow logging in with email and password, creating a session record (token, owning user, expiration) and returning the token as an HttpOnly cookie.
- **FR-004**: The system MUST allow logging out, invalidating the current session so it is no longer accepted afterward.
- **FR-005**: WHEN a request without a valid session reaches an endpoint that manages a user's own subscriptions, the system SHALL respond with HTTP 401.
- **FR-006**: `GET /v1/search` and `GET /v1/config` MUST continue to work without a session, unchanged from Etapas 1 and 2.

### Suscripciones

- **FR-007**: An authenticated user MUST be able to create a subscription with a search text and structured filters, owned by that user.
- **FR-008**: A subscription's filters MUST be validated against the filters declared in `installation.yaml` (reusing the Etapa 1 filter module); a request with an undeclared filter key MUST be rejected with HTTP 422.
- **FR-009**: The system MUST compute an embedding for a subscription's search text, using the same embedding pipeline as search, at creation time and whenever the text is updated.
- **FR-010**: An authenticated user MUST be able to list their own subscriptions, and to pause, resume, or delete one of their own subscriptions.
- **FR-011**: WHEN a user attempts to view or modify a subscription they do not own, the system SHALL respond with HTTP 403 or 404, and MUST NOT reveal the subscription's contents.

### Evaluación de documentos nuevos

- **FR-012**: WHEN ingestion of a document completes successfully (a genuinely new document, not one where `ya_existia` is true), the system SHALL evaluate it against every active (non-paused) subscription.
- **FR-013**: Evaluating a subscription against a document MUST first apply the subscription's filters to the document's metadata; a document that does not pass the filter MUST NOT be evaluated semantically for that subscription.
- **FR-014**: A document MUST be considered a match for a subscription when the highest cosine similarity between the subscription's embedding and any of the document's fragments meets or exceeds the configured similarity threshold (the same threshold used by search).
- **FR-015**: A match MUST be recorded at most once per (documento, suscripción) pair, storing the score, the filters that were applied, and the evaluation date.
- **FR-016**: A subscription's last-evaluated timestamp MUST update after it is evaluated against a document, whether or not it matched.
- **FR-017**: A paused subscription MUST NOT be evaluated against new documents.

## Success Criteria

- **SC-001**: Registering a second account with an already-registered email is rejected (HTTP 409), and 0 additional user rows are created.
- **SC-002**: Logging in with a wrong password returns HTTP 401 and creates 0 session rows.
- **SC-003**: Creating, pausing, resuming, and deleting a subscription without a valid session each return HTTP 401 — verified for all 4 operations.
- **SC-004**: Acting on another user's subscription (pause, resume, delete, or read) returns HTTP 403 or 404 for 100% of attempts, verified with 2 distinct user accounts.
- **SC-005**: The existing Etapa 1/2 automated test suite for `GET /v1/search` and `GET /v1/config` continues to pass unmodified (0 changes needed to those tests).
- **SC-006**: Ingesting a document whose text semantically matches an active subscription creates exactly 1 `EvaluacionMatch` row with a score at or above the configured threshold.
- **SC-007**: Ingesting a document that matches semantically but fails a subscription's declared filter creates 0 `EvaluacionMatch` rows for that subscription.
- **SC-008**: Ingesting a document against a *paused* subscription creates 0 `EvaluacionMatch` rows for it, even when the text matches semantically and passes the filters.
- **SC-009**: Re-ingesting an already-existing document (`ya_existia = true`) creates 0 additional `EvaluacionMatch` rows and leaves every subscription's last-evaluated timestamp unchanged.

## Clarifications

- **Q**: ¿Qué mecanismo de autenticación se usa? **A**: Sesiones con cookie HttpOnly, respaldadas por una tabla `sesiones` en Postgres (token, usuario, expiración) — no JWT. Permite invalidar una sesión de verdad al cerrar sesión, y es coherente con el resto del proyecto (nada stateless todavía). (2026-09-23)
- **Q**: ¿`GET /v1/search` pasa a requerir cuenta? **A**: No. Sigue público, sin cambios respecto a las Etapas 1 y 2; el login se exige solo para gestionar suscripciones. (2026-09-23)
- **Q**: ¿"Consultas guardadas" es una entidad separada de "Suscripción"? **A**: No. El modelo conceptual del design spec (sección 5) ya muestra únicamente `Suscripcion` bajo `Usuario`, sin una entidad de búsqueda guardada aparte. "Guardar una búsqueda" es crear una suscripción; no hace falta que además tenga notificaciones activas para existir (eso es indistinto hasta la Etapa 4, que todavía no entrega nada). (2026-09-23)
- **Q**: ¿La evaluación de documentos nuevos contra suscripciones es síncrona o asíncrona? **A**: Síncrona, dentro del mismo flujo de `ingerir_documento`, tal como habilita la sección 6.3 del design spec para un volumen chico. Se revisa si hace falta separarla en tareas asíncronas cuando crezca el volumen de suscripciones o de documentos. (2026-09-23)
- **Q**: ¿Qué pasa con los campos de frecuencia y canales de notificación de una suscripción? **A**: El modelo de datos los contempla (sección 4.5 del design spec), pero sin ninguna lógica de envío — eso es la Etapa 4. Se guardan como configuración inerte para no requerir otra migración en la etapa siguiente.
- **Q**: ¿Qué pasa con un documento previamente ingerido cuyo `estado` pasó a `error` y se reprocesa más tarde? **A**: Fuera de alcance de esta etapa; la evaluación de suscripciones se dispara únicamente en el flujo normal de `ingerir_documento` cuando termina en `estado = "completo"` para un documento nuevo. Un reprocesamiento manual de documentos fallidos no existe todavía (ni en esta etapa ni en las anteriores). (2026-09-23)
