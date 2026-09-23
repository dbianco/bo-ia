"""Orquesta una corrida de conector: descubre, ingiere cada documento vía
el motor común, y registra el resultado en `EjecucionFuente` (sección 4.4
del design spec, FR-001, FR-002, FR-003).
"""
from __future__ import annotations

import datetime
import logging

from sqlalchemy.orm import Session

from src.connectors.protocol import Conector, ErrorDescubrimiento
from src.db.models import EjecucionFuente, Fuente
from src.ingestor.contract import ingerir_documento
from src.processor.embeddings import EmbeddingProvider

logger = logging.getLogger("bo-ia.scheduler")


def _ahora() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def ejecutar_conector(
    session: Session,
    embedder: EmbeddingProvider,
    fuente: Fuente,
    conector: Conector,
    config: dict,
    *,
    version_conector: str,
) -> EjecucionFuente:
    """Corre `conector.descubrir()` para `fuente`, ingiere cada documento
    normalizado y registra la ejecución. Un error en un documento
    individual (de descubrimiento o de ingesta) se cuenta como error de la
    ejecución sin perder el resto (FR-003); un error del conector completo
    (p. ej. no se pudo conectar) marca toda la ejecución como `fallida`,
    pero igual queda registrada con lo que se llegó a procesar.
    """
    ejecucion = EjecucionFuente(
        fuente_id=fuente.id,
        inicio=_ahora(),
        estado="en_curso",
        version_conector=version_conector,
    )
    session.add(ejecucion)
    session.flush()
    session.commit()

    descubiertos = nuevos = existentes = errores = 0
    detalle_errores: list[dict] = []
    estado_final = "completada"

    try:
        for item in conector.descubrir(fuente_clave=fuente.clave, config=config):
            descubiertos += 1

            if isinstance(item, ErrorDescubrimiento):
                errores += 1
                detalle_errores.append({"identificador_externo": item.identificador_externo, "error": item.error})
                continue

            try:
                resultado = ingerir_documento(session, embedder, item)
                if resultado.ya_existia:
                    existentes += 1
                else:
                    nuevos += 1
            except Exception as exc:  # error de un documento puntual, no de toda la corrida
                errores += 1
                detalle_errores.append({"identificador_externo": item.identificador_externo, "error": str(exc)})
                logger.warning(
                    "Error ingiriendo documento %s de la fuente %s: %s",
                    item.identificador_externo,
                    fuente.clave,
                    exc,
                )
    except Exception as exc:  # el conector completo falló (p. ej. no se pudo conectar)
        estado_final = "fallida"
        detalle_errores.append({"identificador_externo": None, "error": str(exc)})
        logger.error("La ejecución de la fuente %s falló: %s", fuente.clave, exc)

    ejecucion.fin = _ahora()
    ejecucion.estado = estado_final
    ejecucion.descubiertos = descubiertos
    ejecucion.nuevos = nuevos
    ejecucion.existentes = existentes
    ejecucion.errores = errores
    ejecucion.detalle_errores = detalle_errores
    session.commit()
    return ejecucion
