"""Crea y despacha las entregas de notificación de un match nuevo
(sección 4.6 del design spec, FR-001 a FR-004, FR-007, FR-008).

Llamado directamente desde `evaluar_documento` (mismo patrón que ya usa
`ingerir_documento` para llamar a `evaluar_documento`, ver Etapa 3): la
sección 6.3 del design spec dibuja "genera una entrega pendiente" como
parte del mismo flujo, no como un paso opcional que cada llamador deba
recordar disparar.
"""
from __future__ import annotations

import datetime
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import EntregaNotificacion, EvaluacionMatch
from src.notifications.email import EnvioCorreoFallido, enviar_correo

logger = logging.getLogger("bo-ia.notifications")

CANAL_DEFAULT = ("bandeja",)


def _ahora() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _cuerpo_correo(match: EvaluacionMatch) -> str:
    documento = match.documento
    return (
        f"Hay un documento nuevo que coincide con tu suscripción "
        f"'{match.suscripcion.texto_busqueda}':\n\n"
        f"{documento.titulo or documento.identificador_externo}\n"
        f"{documento.url_fuente}\n"
    )


def _intentar_entrega(entrega: EntregaNotificacion, match: EvaluacionMatch) -> None:
    if entrega.canal == "bandeja":
        entrega.estado = "entregada"
        entrega.fecha_intento = _ahora()
        return

    # canal == "correo". Doble red de seguridad para FR-007: `enviar_correo`
    # ya convierte los errores esperados de SMTP en `EnvioCorreoFallido`,
    # pero cualquier excepción no prevista tampoco debe interrumpir la
    # ingesta del documento ni el resto de la evaluación.
    try:
        enviar_correo(
            destinatario=match.suscripcion.usuario.email,
            asunto=f"Nuevo documento para tu suscripción: {match.suscripcion.texto_busqueda}",
            cuerpo=_cuerpo_correo(match),
        )
        entrega.estado = "entregada"
    except EnvioCorreoFallido as exc:
        entrega.estado = "fallida"
        entrega.error_proveedor = str(exc)
    except Exception as exc:  # red de seguridad adicional, ver docstring
        entrega.estado = "fallida"
        entrega.error_proveedor = str(exc)
        logger.error("Error inesperado enviando correo para la entrega %s: %s", entrega.id, exc)

    entrega.fecha_intento = _ahora()


def crear_entregas_para_match(session: Session, match: EvaluacionMatch) -> None:
    canales = match.suscripcion.canales or list(CANAL_DEFAULT)
    for canal in canales:
        existente = session.scalar(
            select(EntregaNotificacion).where(
                EntregaNotificacion.match_id == match.id, EntregaNotificacion.canal == canal
            )
        )
        if existente is not None:
            continue

        entrega = EntregaNotificacion(match_id=match.id, canal=canal, estado="pendiente")
        session.add(entrega)
        session.flush()
        _intentar_entrega(entrega, match)

    session.commit()
