# Tasks: Etapa 3 — Clientes y suscripciones

Framework: spec-kit (track default)
Feature ID: f_01m37xd2yt0zvrz0rkbb46x6qz
Fuente: `plan.md` de esta feature (Project Structure y Research)

Orden: toda dependencia aparece antes que la tarea que depende de ella. `[P]` marca tareas que pueden hacerse en paralelo (no dependen entre sí y tocan archivos distintos).

## Tasks

### Modelo de datos y migración

- [ ] T001 Agregar los modelos `Usuario`, `Sesion`, `Suscripcion`, `EvaluacionMatch` en `backend/src/db/models.py`
- [ ] T002 Escribir la migración Alembic que crea `usuarios`, `sesiones`, `suscripciones`, `evaluaciones_match`, con `downgrade` completo, en `backend/src/db/migrations/versions/`, depends on T001
- [ ] T003 Extender el ciclo `upgrade → downgrade → upgrade` de `backend/tests/test_migrations.py` para la nueva revisión, depends on T002

### Seguridad y sesiones (TDD)

- [ ] T004 [P] Escribir tests que fallen para `hash_password`/`verificar_password` (el hash difiere de la contraseña en texto plano, verificación correcta e incorrecta) en `backend/tests/auth/test_security.py` (FR-002), depends on T002
- [ ] T005 Implementar `hash_password`/`verificar_password` con `hashlib.pbkdf2_hmac` en `backend/src/auth/security.py`, depends on T004
- [ ] T006 [P] Escribir tests que fallen para `crear_sesion`/`obtener_usuario_de_sesion`/`invalidar_sesion` (token válido, expirado, inexistente, invalidado) en `backend/tests/auth/test_sessions.py` (FR-003, FR-004), depends on T002
- [ ] T007 Implementar `crear_sesion`/`obtener_usuario_de_sesion`/`invalidar_sesion` en `backend/src/auth/sessions.py`, depends on T005, depends on T006

### Filtros para suscripciones (TDD)

- [ ] T008 [P] Escribir tests que fallen para `construir_filtros_suscripcion` (snapshot con tipo y valor, rechaza clave no declarada) y `cumple_filtros` (selección, rango numérico, sin filtros declarados) en `backend/tests/search/test_filters.py` (FR-008, FR-013), depends on T002
- [ ] T009 Implementar `construir_filtros_suscripcion` y `cumple_filtros` en `backend/src/search/filters.py`, depends on T008

### Endpoints de autenticación (TDD)

- [ ] T010 [P] Escribir tests que fallen para `POST /v1/auth/registro`, `/login`, `/logout` (email duplicado → 409, contraseña incorrecta → 401, cookie de sesión seteada, logout invalida la sesión) en `backend/tests/api/test_auth.py` (FR-001 a FR-004, SC-001, SC-002), depends on T007
- [ ] T011 Implementar el router de autenticación en `backend/src/api/auth.py`, depends on T010
- [ ] T012 Agregar `get_usuario_actual` (dependencia que devuelve 401 sin sesión válida) en `backend/src/api/deps.py` (FR-005), depends on T007

### Suscripciones (TDD)

- [ ] T013 [P] Escribir tests que fallen para crear, listar, pausar, reanudar y borrar una suscripción propia; 401 sin sesión en cada operación; 404 al actuar sobre una suscripción ajena, en `backend/tests/api/test_suscripciones.py` (FR-007, FR-010, FR-011, SC-003, SC-004), depends on T009, depends on T012
- [ ] T014 Implementar el router de suscripciones en `backend/src/api/suscripciones.py`, depends on T013
- [ ] T015 Registrar los routers de `auth` y `suscripciones` en `backend/src/api/main.py`, depends on T011, depends on T014

### Evaluación de documentos nuevos (TDD)

- [ ] T016 [P] Escribir tests que fallen para `evaluar_documento`: un match queda registrado con score, filtros aplicados y fecha (SC-006); un filtro que no matchea da 0 matches (SC-007); una suscripción pausada da 0 matches (SC-008); re-evaluar el mismo documento no duplica el match, en `backend/tests/subscriptions/test_evaluator.py`, depends on T009
- [ ] T017 Implementar `evaluar_documento` en `backend/src/subscriptions/evaluator.py` (FR-012 a FR-017), depends on T016
- [ ] T018 Llamar a `evaluar_documento` desde `ingerir_documento` al completar un documento genuinamente nuevo, en `backend/src/ingestor/contract.py` (FR-012, SC-009), depends on T017

### Regresión y verificación

- [ ] T019 Confirmar que la suite existente de `GET /v1/search` y `GET /v1/config` (Etapas 1 y 2) sigue pasando sin cambios (FR-006, SC-005), depends on T018
- [ ] T020 [P] Actualizar `README.md` con los endpoints nuevos (`/v1/auth/*`, `/v1/suscripciones/*`), depends on T015
- [ ] T021 Correr la suite completa (migración, seguridad, sesiones, filtros, auth, suscripciones, evaluación, regresión) y confirmar cada escenario de aceptación y criterio de éxito de `spec.md`; registrar los resultados como evidencia para la fase `verify`, depends on T003, depends on T019, depends on T020
