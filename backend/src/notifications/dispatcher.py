"""Crea las entregas de notificación de un match nuevo (sección 4.6 del
design spec, FR-001 a FR-004).

It only writes rows, in the transaction of the match: the inbox is one of them,
and the emails are sent later, from `outbox.py`.
"""
from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import EntregaNotificacion, EvaluacionMatch

CANAL_DEFAULT = ("bandeja",)


def crear_entregas_para_match(
    session: Session, match: EvaluacionMatch, *, now: datetime.datetime | None = None
) -> None:
    """One delivery for each channel of the subscription, if it is not there yet.
    The caller commits."""
    now = now or datetime.datetime.now(datetime.UTC)
    existentes = set(
        session.scalars(select(EntregaNotificacion.canal).where(EntregaNotificacion.match_id == match.id))
    )
    for canal in match.suscripcion.canales or list(CANAL_DEFAULT):
        if canal in existentes:
            continue
        entrega = EntregaNotificacion(
            match_id=match.id,
            canal=canal,
            estado="entregada" if canal == "bandeja" else "pendiente",
            fecha_intento=now if canal == "bandeja" else None,
            # As it is now: changing it later does not move what is already waiting.
            frequency=match.suscripcion.frecuencia_notificacion,
            created_at=now,
            next_attempt_at=now,
        )
        session.add(entrega)
    session.flush()
