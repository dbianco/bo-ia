# Evidencia de verificación — Etapa 4 (notificaciones)

Feature ID: `f_01m39nchns3qv6gpdzp34pg4pm` · Fecha: 2026-09-24

Cruza cada escenario de aceptación y criterio de éxito de `spec.md` contra la verificación real hecha durante `implement`. Todo lo marcado ✅ se corrió con comandos reales: `pytest` contra Postgres real, `alembic upgrade/downgrade` real, `docker compose up --build` real, y `curl` contra el stack levantado con el modelo de embeddings real (sin SMTP configurado, para probar la falla controlada de verdad).

## Acceptance scenarios (spec.md)

| # | Escenario | Estado | Evidencia |
|---|---|---|---|
| 1 | Match nuevo → una entrega pendiente por canal declarado (o solo "bandeja") | ✅ | `test_sin_canales_declarados_crea_una_entrega_bandeja`, `test_dos_canales_declarados_crea_dos_entregas` |
| 2 | Entrega "bandeja" → entregada de inmediato, sin llamada externa | ✅ | `test_bandeja_no_llama_a_smtp`; confirmado en real (`entregada`, `fecha_intento` seteado, 0 llamadas SMTP) |
| 3 | Entrega "correo" con SMTP funcionando → intenta enviar, éxito → entregada | ✅ | `test_correo_exitoso_queda_entregada`, `test_enviar_correo_exitoso_usa_smtp_configurado` (mock de `smtplib.SMTP`) |
| 4 | Entrega "correo" sin SMTP o con fallo → fallida, con motivo, sin interrumpir la ingesta | ✅ | `test_correo_fallido_queda_fallida_con_error_y_no_propaga`, `test_enviar_correo_sin_smtp_host_configurado_falla`, `test_enviar_correo_con_error_de_smtp_levanta_envio_correo_fallido`; **confirmado en real**: `POST /v1/documentos` contra el stack sin `SMTP_HOST` devolvió `200` (ingesta completa) y la entrega de correo quedó `fallida` con `error_proveedor = "SMTP_HOST no está configurado"` |
| 5 | Usuario autenticado ve solo sus propias entregas | ✅ | `test_listar_notificaciones_propias`, `test_listar_notificaciones_no_ve_las_de_otro_usuario` |
| 6 | Suscripción con canal no válido → rechazada | ✅ | `test_crear_suscripcion_con_canal_invalido_devuelve_422` |
| 7 | Reevaluar un match ya procesado → no duplica entrega por canal | ✅ | `test_recrear_entregas_para_el_mismo_match_no_duplica` |

## Success Criteria (spec.md)

| Criterio | Estado | Evidencia |
|---|---|---|
| SC-001: 2 canales → 2 entregas; sin canales → 1 (bandeja) | ✅ | `test_dos_canales_declarados_crea_dos_entregas`, `test_sin_canales_declarados_crea_una_entrega_bandeja` |
| SC-002: reevaluar un match ya procesado → 0 entregas nuevas por (match, canal) | ✅ | `test_recrear_entregas_para_el_mismo_match_no_duplica` |
| SC-003: "bandeja" entregada de inmediato, 0 llamadas de red | ✅ | `test_bandeja_no_llama_a_smtp` (mock de `smtplib.SMTP` con `assert_not_called`) |
| SC-004: `GET /v1/notificaciones` → 401 sin sesión; 100% de filas propias con sesión | ✅ | `test_listar_notificaciones_sin_sesion_devuelve_401`, `test_listar_notificaciones_no_ve_las_de_otro_usuario`; confirmado en real con dos usuarios distintos |
| SC-005: envío SMTP exitoso (mockeado) → entregada con `fecha_intento` | ✅ | `test_correo_exitoso_queda_entregada`, `test_enviar_correo_exitoso_usa_smtp_configurado` |
| SC-006: envío SMTP fallido (mockeado o SMTP no configurado) → fallida con `error_proveedor`, ingesta completa igual | ✅ | `test_correo_fallido_queda_fallida_con_error_y_no_propaga`; **confirmado en real**: `POST /v1/documentos` con `SMTP_HOST` vacío devolvió `estado: "completo"` y la entrega de correo quedó `fallida` |
| SC-007: suscripción con canal no declarado → 422, 0 filas | ✅ | `test_crear_suscripcion_con_canal_invalido_devuelve_422` |

## Trazabilidad FR → test

| FR | Cubierto por |
|---|---|
| FR-001, FR-002, FR-003 | `tests/notifications/test_dispatcher.py` |
| FR-004 | `test_bandeja_no_llama_a_smtp` |
| FR-005 | `tests/api/test_notificaciones.py` |
| FR-006, FR-008, FR-009 | `tests/notifications/test_email.py`, `test_correo_exitoso_queda_entregada` |
| FR-007 | `test_correo_fallido_queda_fallida_con_error_y_no_propaga`, `test_error_inesperado_en_el_envio_tampoco_propaga`; confirmado en real sin SMTP configurado |
| FR-010 | `tests/api/test_suscripciones.py::test_crear_suscripcion_con_canales_validos`, `test_crear_suscripcion_con_canal_invalido_devuelve_422` |

## Checklist de la fase `verify`

- **Lint (ruff):** `ruff check .` → 0 hallazgos.
- **Tests:** 128/128 en verde (`pytest -m "not slow and not docker and not live"`, incluye el modelo real de embeddings en los tests marcados no-`slow` que ya usaban `FakeEmbeddingProvider`/`_EmbedderFijo`; se agregan 19 tests nuevos de esta etapa: 3 de `test_email.py`, 7 de `test_dispatcher.py`, 3 de `test_notificaciones.py`, 3 de `test_suscripciones.py` + `test_migrations.py` actualizado).
- **Smoke Docker real:** `pytest -m docker` → 1/1 en verde. Reconstruyó la imagen con el código de esta etapa (incluidas las variables `SMTP_*` propagadas en `docker-compose.yml`) y arrancó sin caerse.
- **Verificación manual real contra el stack levantado**, con el modelo de embeddings real y `SMTP_HOST` intencionalmente vacío (para probar FR-007 de verdad, no solo mockeado):
  1. Registro y login reales (`curl -c cookies.txt`), cookie de sesión seteada.
  2. `POST /v1/suscripciones` con `"canales": ["bandeja", "correo"]`.
  3. `POST /v1/documentos` con un documento nuevo semánticamente relacionado a la suscripción → `estado: "completo"`, la ingesta no se interrumpió pese al fallo de SMTP.
  4. `GET /v1/notificaciones` devolvió exactamente 2 entregas: `bandeja` → `entregada`; `correo` → `fallida`.
  5. Confirmado además consultando Postgres directamente (`entregas_notificacion`): `error_proveedor = "SMTP_HOST no está configurado"` en la fila de correo, `reintentos = 0` en ambas (sin reintento automático, por diseño).
- **files_changed:** ver `plan.md` → Project Structure para el árbol final (incluye `docker-compose.yml`, agregado a la lista original de Modificados).

## Bugs reales encontrados y corregidos durante `implement`

1. **`EvaluacionMatch` no tenía relación `documento`**: `dispatcher.py` necesitaba `match.documento` para armar el cuerpo del correo, pero el modelo solo tenía `documento_id`, sin `relationship`. Corregido agregando `documento: Mapped[Documento] = relationship()` a `EvaluacionMatch`, junto con `entregas` (`back_populates`).
2. **Import sin uso en `test_notificaciones.py`**: al cambiar de `FakeEmbeddingProvider` a un `_EmbedderFijo` propio (para garantizar un match determinístico por encima del umbral, en vez de depender del hash del texto), quedó el import viejo sin usar. Detectado por `ruff check`, corregido con `ruff check --fix`.

## Gaps conocidos, sin resolver

1. **Sin reintento automático de entregas fallidas**: decisión ya tomada en `spec.md` (Clarifications), desviación consciente del alcance original de la sección 8. El campo `reintentos` existe en el modelo pero nada lo incrementa todavía; una entrega `fallida` queda así hasta que una etapa futura agregue el mecanismo.
2. **Sin Mailhog ni forma de ver un correo "real" en desarrollo local**: decisión ya tomada en `spec.md`; los tests mockean `smtplib.SMTP`, y la verificación real de esta etapa usa intencionalmente `SMTP_HOST` vacío para probar la rama de fallo controlado, no un envío exitoso real. Probar un envío exitoso real requiere credenciales SMTP propias del usuario en `.env`.
3. **Sin endpoint para reintentar o descartar una entrega fallida manualmente**: la bandeja (`GET /v1/notificaciones`) es de solo lectura en esta etapa.
4. **Sin pantallas en la web**: esta etapa es solo API, igual que la Etapa 3.
