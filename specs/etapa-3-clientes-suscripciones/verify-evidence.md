# Evidencia de verificación — Etapa 3 (clientes y suscripciones)

Feature ID: `f_01m37xd2yt0zvrz0rkbb46x6qz` · Fecha: 2026-09-23

Cruza cada escenario de aceptación y criterio de éxito de `spec.md` contra la verificación real hecha durante `implement`. Todo lo marcado ✅ se corrió con comandos reales: `pytest` contra Postgres real, `alembic upgrade/downgrade` real, `docker compose up --build` real, y `curl` contra el stack levantado con el modelo de embeddings real.

## Acceptance scenarios (spec.md)

| # | Escenario | Estado | Evidencia |
|---|---|---|---|
| 1 | Registro crea una cuenta | ✅ | `tests/api/test_auth.py::test_registro_crea_una_cuenta`; confirmado con `curl` real |
| 2 | Login crea una sesión (cookie) | ✅ | `test_login_con_credenciales_correctas_setea_cookie_de_sesion`; confirmado con `curl` real |
| 3 | Logout invalida la sesión | ✅ | `test_logout_invalida_la_sesion` |
| 4 | Crear una suscripción con embedding y estado activa | ✅ | `test_crear_suscripcion_queda_activa_y_con_embedding`; confirmado con `curl` real |
| 5 | Pausar/reanudar/borrar propia; rechazo sobre ajena | ✅ | `test_pausar_reanudar_y_borrar_una_suscripcion_propia`, `test_pausar_una_suscripcion_ajena_devuelve_404`, `test_borrar_una_suscripcion_ajena_devuelve_404` |
| 6 | Match semántico registrado con score/filtros/fecha | ✅ | `tests/subscriptions/test_evaluator.py::test_documento_que_matchea_registra_un_evaluacion_match`; **confirmado con datos reales**: ingesta real de un documento nuevo contra una suscripción real produjo `EvaluacionMatch(score=0.7896)` con el modelo de embeddings real, dentro del stack de Docker |
| 7 | Filtro que no matchea → 0 matches | ✅ | `test_documento_que_no_pasa_el_filtro_no_registra_match` |
| 8 | Suscripción pausada → no se evalúa | ✅ | `test_suscripcion_pausada_no_se_evalua` |
| 9 | `GET /v1/search`/`GET /v1/config` siguen públicos | ✅ | Suite completa de las Etapas 1 y 2 (`test_search.py`, `test_search_hybrid.py`, `test_search_filters.py`, `test_config.py`) pasa sin ningún cambio |

## Success Criteria (spec.md)

| Criterio | Estado | Evidencia |
|---|---|---|
| SC-001: email duplicado → 409, 0 filas extra | ✅ | `test_registro_con_email_duplicado_devuelve_409` |
| SC-002: contraseña incorrecta → 401, 0 sesiones | ✅ | `test_login_con_contrasena_incorrecta_devuelve_401_sin_crear_sesion` |
| SC-003: 401 sin sesión en crear/pausar/reanudar/borrar | ✅ | `test_crear_suscripcion_sin_sesion_devuelve_401`, `test_listar_suscripciones_sin_sesion_devuelve_401`; pausar/reanudar/borrar comparten la misma dependencia `get_usuario_actual`, verificado por construcción y por los tests de `_obtener_propia` |
| SC-004: 403/404 sobre suscripción ajena, 2 usuarios | ✅ | `test_pausar_una_suscripcion_ajena_devuelve_404`, `test_borrar_una_suscripcion_ajena_devuelve_404`, `test_listar_suscripciones_devuelve_solo_las_propias` |
| SC-005: suite de `GET /v1/search`/`GET /v1/config` sin cambios | ✅ | 114/114 tests en verde, incluida toda la suite de búsqueda de las Etapas 1 y 2 sin modificar un solo archivo de esos tests |
| SC-006: match semántico → exactamente 1 `EvaluacionMatch` | ✅ | Test + confirmado en real (score 0.7896) |
| SC-007: filtro que no pasa → 0 matches | ✅ | `test_documento_que_no_pasa_el_filtro_no_registra_match` |
| SC-008: suscripción pausada → 0 matches | ✅ | `test_suscripcion_pausada_no_se_evalua` |
| SC-009: re-ingesta de documento existente → 0 matches nuevos | ✅ | Cubierto indirectamente: `ingerir_documento` solo llama a `evaluar_documento` en la rama de documento nuevo (`ya_existia=False`); `test_reevaluar_el_mismo_documento_no_duplica_el_match` cubre la idempotencia de `evaluar_documento` en sí |

## Trazabilidad FR → test

| FR | Cubierto por |
|---|---|
| FR-001, FR-002 | `tests/auth/test_security.py`, `tests/api/test_auth.py` |
| FR-003, FR-004 | `tests/auth/test_sessions.py`, `tests/api/test_auth.py` |
| FR-005, FR-006 | `src/api/deps.py::get_usuario_actual`; suite existente de search/config sin cambios |
| FR-007, FR-008, FR-009 | `tests/api/test_suscripciones.py`, `tests/search/test_filters.py` |
| FR-010, FR-011 | `tests/api/test_suscripciones.py` |
| FR-012 a FR-017 | `tests/subscriptions/test_evaluator.py` |

## Checklist de la fase `verify`

- **Lint (ruff):** `ruff check src tests` → 0 hallazgos.
- **Tests:** 114/114 en verde (`pytest --ignore=tests/smoke -m "not live"`, incluye el modelo real de embeddings).
- **Smoke Docker real:** `pytest -m docker tests/smoke/test_docker_up.py` → 1/1 en verde. Reconstruyó la imagen con el código de esta etapa y arrancó sin caerse.
- **Verificación manual real contra el stack levantado:** registro, login (cookie seteada), creación de suscripción, listado, 401 sin sesión — todo con `curl` real. Ingesta real de un documento nuevo (`POST /v1/documentos`) produjo un match real (`EvaluacionMatch`, score 0.7896) contra la suscripción creada, con `ultima_evaluacion` actualizada — confirmado consultando Postgres directamente.
- **files_changed:** ver `plan.md` → Project Structure para el árbol final.

## Bugs reales encontrados y corregidos durante `implement`

1. **`backend/tests/conftest.py` no truncaba `usuarios`**: los tests de esta etapa insertaban el mismo email (`cliente@example.org`) en distintos tests, y como `usuarios` no estaba en el `TRUNCATE` de `conftest.py`, la fila sobrevivía entre tests y el segundo test que intentaba crear el mismo usuario chocaba con la unique constraint. Postgres `TRUNCATE ... CASCADE` sí limpia en cascada las tablas dependientes (`sesiones`, `suscripciones`, `evaluaciones_match`) una vez que `usuarios` está en la lista — no hacía falta nombrarlas todas, solo agregar la tabla raíz. Corregido agregando `usuarios` a la lista.
2. **Riesgo real evitado antes de que ocurriera**: la llamada a `evaluar_documento` se agregó primero dentro del mismo bloque `try/except` de fragmentación/embeddings de `ingerir_documento`. Se detectó en revisión (no en un test que fallara) que, si `evaluar_documento` lanzaba una excepción, el `except` de ese bloque marcaría el documento como `estado="error"` aunque ya se hubiera ingerido correctamente — perdiendo el éxito real de la ingesta por un fallo en un paso secundario. Se movió la llamada fuera de ese `try/except`, después del `return` implícito de la ruta exitosa.

## Gaps conocidos, sin resolver

1. **Sin pantallas de login/registro en la web**: decisión ya tomada en `plan.md`; esta etapa es solo API.
2. **Cookie de sesión sin `Secure`**: no se fuerza HTTPS todavía (el proyecto corre en HTTP en desarrollo); antes de un despliegue real detrás de HTTPS, `secure=True` debería activarse condicionalmente.
3. **PBKDF2 en vez de `bcrypt`/`argon2`**: decisión consciente para no sumar una dependencia nueva en esta primera versión (ver `plan.md` → Research); revisar si la superficie de ataque real lo justifica.
4. **SC-009 no tiene un test end-to-end directo** que ingiera el mismo documento dos veces y confirme 0 matches adicionales a través de la API completa; la cobertura es indirecta (por construcción de `ingerir_documento` + la idempotencia ya probada de `evaluar_documento`). Se consideró suficiente para el alcance de esta etapa.
