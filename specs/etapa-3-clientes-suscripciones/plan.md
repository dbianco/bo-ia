# Plan: Etapa 3 — Clientes y suscripciones

Framework: spec-kit (track default)
Feature ID: f_01m37xd2yt0zvrz0rkbb46x6qz
Fuente: `spec.md` de esta feature

## Technical Context

- **Lenguaje y versión:** Python 3.12, mismo backend consolidado.
- **Dependencias nuevas:** ninguna. El hash de contraseña usa `hashlib.pbkdf2_hmac` (SHA-256, 600.000 iteraciones, la recomendación vigente de OWASP para PBKDF2) y el token de sesión usa `secrets.token_urlsafe`, ambos de la librería estándar — evita sumar `bcrypt`/`argon2-cffi` para esta primera versión.
- **Almacenamiento:** 4 tablas nuevas — `usuarios`, `sesiones`, `suscripciones` (con `embedding` `Vector(1024)`, igual que `fragmentos`), `evaluaciones_match`.
- **Herramientas de testing:** pytest, igual que las etapas anteriores; `FakeEmbeddingProvider` para no depender del modelo real en los tests de evaluación.
- **Plataforma objetivo:** sin cambios.
- **Objetivos de performance y restricciones:** la evaluación de un documento nuevo contra suscripciones activas es síncrona, dentro de `ingerir_documento` (decisión ya tomada en `spec.md`); el volumen esperado (una instalación, unas pocas suscripciones) no justifica separarla en una tarea aparte todavía.

## Constitution Check

- **Sin datos personales en logs:** el email y la contraseña son datos de cuenta; la contraseña nunca se loguea ni se guarda en texto plano (FR-002). El email sí se persiste (necesario para login) pero no se emite en logs de error.
- **Timeout y retry en llamadas HTTP salientes:** no aplica; esta etapa no agrega llamadas salientes nuevas.
- **Migraciones de esquema reversibles con rollback probado:** una revisión Alembic nueva crea las 4 tablas, con `downgrade` completo, probada con el mismo patrón `upgrade → downgrade → upgrade`.
- **Cambios de API pública aditivos:** todos los endpoints de esta etapa son nuevos (`/v1/auth/*`, `/v1/suscripciones/*`); `GET /v1/search` y `GET /v1/config` no cambian (FR-006, SC-005).
- **Secretos desde el entorno:** sin cambios; no hay credenciales de terceros nuevas. El hash de contraseña no requiere una clave secreta externa (PBKDF2 con sal por usuario, no HMAC con clave del servidor).
- **Tests en CI antes de mergear:** se agregan al mismo `ci.yml`, sin markers nuevos.
- **Accesibilidad:** no aplica; esta etapa no agrega pantallas a la interfaz web (solo API). Un formulario de login/registro en la web queda fuera de esta etapa — no estaba en el alcance acordado en `spec.md`.

## Project Structure

Lista inicial; se actualiza con el nombre real de la migración y el árbol final antes de `verify`.

Lista final real, actualizada tras `implement`.

Modificados:

- `backend/src/db/models.py`
- `backend/src/ingestor/contract.py` (llama a `evaluar_documento` al completar un documento nuevo, fuera del try/except de fragmentación para que un error de evaluación no revierta un documento ya ingerido bien)
- `backend/src/api/main.py` (registra los routers nuevos)
- `backend/src/api/deps.py` (`COOKIE_SESION`, `get_usuario_actual`)
- `backend/src/search/filters.py` (se extiende: `construir_filtros_suscripcion`, `cumple_filtros`)
- `backend/tests/test_migrations.py`
- `backend/tests/conftest.py` (agrega `usuarios` al `TRUNCATE`; sin él, `sesiones`/`suscripciones` se filtraban entre tests)
- `backend/tests/search/test_filters.py` (se extiende con los tests de `construir_filtros_suscripcion`/`cumple_filtros`)
- `README.md`

Nuevos:

- `backend/src/db/migrations/versions/561281315b74_create_usuarios_suscripciones.py`
- `backend/src/auth/__init__.py`
- `backend/src/auth/security.py` (`hash_password`, `verificar_password`)
- `backend/src/auth/sessions.py` (`crear_sesion`, `obtener_usuario_de_sesion`, `invalidar_sesion`)
- `backend/src/api/auth.py` (`POST /v1/auth/registro`, `POST /v1/auth/login`, `POST /v1/auth/logout`)
- `backend/src/api/suscripciones.py` (`POST/GET /v1/suscripciones`, `POST .../pausar`, `POST .../reanudar`, `DELETE /v1/suscripciones/{id}`)
- `backend/src/subscriptions/__init__.py`
- `backend/src/subscriptions/evaluator.py` (`evaluar_documento`)
- `backend/tests/auth/__init__.py`
- `backend/tests/auth/test_security.py`
- `backend/tests/auth/test_sessions.py`
- `backend/tests/api/test_auth.py`
- `backend/tests/api/test_suscripciones.py`
- `backend/tests/subscriptions/__init__.py`
- `backend/tests/subscriptions/test_evaluator.py`
- `specs/etapa-3-clientes-suscripciones/spec.md`
- `specs/etapa-3-clientes-suscripciones/plan.md`
- `specs/etapa-3-clientes-suscripciones/tasks.md`
- `specs/etapa-3-clientes-suscripciones/verify-evidence.md`

## Research

- **Hash de contraseña con la librería estándar (`hashlib.pbkdf2_hmac`), no `bcrypt`/`argon2-cffi`:** evita una dependencia nueva para esta primera versión de autenticación. PBKDF2-SHA256 con 600.000 iteraciones (recomendación de OWASP 2023) es una opción reconocida, aunque `argon2`/`bcrypt` son preferibles a largo plazo; revisar si el proyecto crece en superficie de ataque real.
- **Sesiones respaldadas por tabla (`sesiones`), no JWT:** decisión ya tomada en `spec.md`. El token es opaco (`secrets.token_urlsafe(32)`), la cookie solo lo transporta; toda la validación (existencia, expiración, usuario) pasa por Postgres, igual que el resto del estado del sistema.
- **`Suscripcion.filtros` como snapshot autocontenido, no una referencia a `installation.yaml`:** en vez de revalidar contra los filtros declarados en cada evaluación, `construir_filtros_suscripcion` guarda en la suscripción `{clave: {"tipo": ..., "valor": ...}}` al crearla. `cumple_filtros` (usado tanto por la validación de creación como por `evaluar_documento`) es una función pura que solo necesita ese snapshot y la metadata del documento — no necesita releer `installation.yaml` en cada evaluación, y una suscripción sigue evaluándose de forma consistente aunque la instalación cambie sus filtros declarados después.
- **Similitud de una suscripción por SQL (`cosine_distance`), no en Python:** igual que hace `search.py`, se usa `Fragmento.embedding.cosine_distance(...)` vía SQLAlchemy/pgvector para encontrar el mejor score entre los fragmentos de un documento y el embedding de la suscripción, en vez de traer los vectores a Python y calcular coseno a mano.
- **`evaluar_documento` se llama directamente desde `ingerir_documento`, no vía callback opcional:** el diagrama de flujo de la sección 6.1 del design spec dibuja "evalúa suscripciones" como parte de un único pipeline de ingesta, no como un paso opcional que cada llamador (API, seed, conectores) deba recordar disparar. Se acepta el acoplamiento de `ingestor` hacia `subscriptions` (import en un solo sentido, sin ciclo) a cambio de la garantía de FR-012 sin depender de que cada call site lo invoque.
- **Sin endpoint de lectura individual de una suscripción ajena:** pausar/reanudar/borrar una suscripción que no es del usuario devuelve 404 (no 403), para no confirmarle a un tercero que el `id` existe.
- **Sin pantallas de login en la web:** esta etapa es solo API; la interfaz Jinja2+htmx no cambia. Autenticarse para probar los endpoints se hace con `curl`/`httpx` guardando la cookie, igual que cualquier cliente API.
