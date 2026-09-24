"""Bandeja interna de avisos: GET /v1/notificaciones (FR-005)."""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_session, get_usuario_actual
from src.db.models import EntregaNotificacion, EvaluacionMatch, Suscripcion, Usuario

router = APIRouter()


class EntregaSalida(BaseModel):
    id: int
    canal: str
    estado: str
    fecha_intento: datetime.datetime | None
    documento_id: int
    suscripcion_id: int


@router.get("/v1/notificaciones", response_model=list[EntregaSalida])
def listar_notificaciones(
    usuario: Usuario = Depends(get_usuario_actual), session: Session = Depends(get_session)
) -> list[EntregaSalida]:
    entregas = session.scalars(
        select(EntregaNotificacion)
        .join(EvaluacionMatch, EntregaNotificacion.match_id == EvaluacionMatch.id)
        .join(Suscripcion, EvaluacionMatch.suscripcion_id == Suscripcion.id)
        .where(Suscripcion.usuario_id == usuario.id)
        .order_by(EntregaNotificacion.created_at.desc())
    ).all()
    return [
        EntregaSalida(
            id=entrega.id,
            canal=entrega.canal,
            estado=entrega.estado,
            fecha_intento=entrega.fecha_intento,
            documento_id=entrega.match.documento_id,
            suscripcion_id=entrega.match.suscripcion_id,
        )
        for entrega in entregas
    ]
