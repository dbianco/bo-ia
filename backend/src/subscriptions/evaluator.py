"""Evalúa un documento nuevo contra las suscripciones activas (sección
4.5 del design spec, FR-012 a FR-017). Síncrono, llamado desde
`ingerir_documento` al completar un documento genuinamente nuevo — el
volumen esperado (una instalación, unas pocas suscripciones) no justifica
separarlo en una tarea aparte todavía.
"""
from __future__ import annotations

import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import Documento, EvaluacionMatch, Fragmento, Suscripcion
from src.processor.threshold import umbral_configurado
from src.search.filters import cumple_filtros


def _ahora() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def evaluar_documento(session: Session, documento: Documento) -> None:
    """Para cada suscripción activa: aplica su filtro sobre la metadata
    del documento (FR-013); si pasa, busca la mejor similitud entre el
    embedding de la suscripción y los fragmentos del documento (FR-014);
    si supera el umbral, registra un `EvaluacionMatch` (a lo sumo uno por
    par documento/suscripción, FR-015). `ultima_evaluacion` se actualiza
    siempre que se evalúa, matchee o no (FR-016). Una suscripción pausada
    no se toca (FR-017)."""
    ahora = _ahora()
    umbral = umbral_configurado()
    suscripciones = session.scalars(select(Suscripcion).where(Suscripcion.estado == "activa")).all()

    for suscripcion in suscripciones:
        if not cumple_filtros(documento.metadata_ or {}, suscripcion.filtros):
            suscripcion.ultima_evaluacion = ahora
            continue

        distancia = Fragmento.embedding.cosine_distance(suscripcion.embedding)
        mejor_distancia = session.scalar(
            select(func.min(distancia)).where(
                Fragmento.documento_id == documento.id, Fragmento.embedding.is_not(None)
            )
        )
        suscripcion.ultima_evaluacion = ahora
        if mejor_distancia is None:
            continue

        score = 1.0 - mejor_distancia
        if score < umbral:
            continue

        ya_existe = session.scalar(
            select(EvaluacionMatch).where(
                EvaluacionMatch.documento_id == documento.id,
                EvaluacionMatch.suscripcion_id == suscripcion.id,
            )
        )
        if ya_existe is None:
            session.add(
                EvaluacionMatch(
                    documento_id=documento.id,
                    suscripcion_id=suscripcion.id,
                    score=round(score, 4),
                    filtros_aplicados=suscripcion.filtros,
                    fecha_evaluacion=ahora,
                )
            )

    session.commit()
