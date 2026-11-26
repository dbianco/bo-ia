"""Bandeja interna de avisos: GET /v1/notificaciones (FR-005), with what matched
and why, and the read state of each entry."""
from __future__ import annotations

import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from src.api.deps import get_session, get_usuario_actual
from src.db.models import EntregaNotificacion, EvaluacionMatch, Suscripcion, Usuario
from src.notifications.explain import explain

router = APIRouter()

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class ExcerptPart(BaseModel):
    text: str
    match: bool  # a word that is also in the subscription


class EntregaSalida(BaseModel):
    id: int
    canal: str
    estado: str
    fecha_intento: datetime.datetime | None
    read_at: datetime.datetime | None
    created_at: datetime.datetime
    documento_id: int
    suscripcion_id: int
    texto_busqueda: str
    # Where to find the document.
    titulo: str | None
    url_fuente: str
    fecha: datetime.date
    notice_number: str | None
    page: int | None
    first_page: int | None
    last_page: int | None
    # Why it matched. No shared words: by its meaning.
    score: float
    filtros: dict[str, str]
    excerpt: list[ExcerptPart]
    shared_words: list[str]


def _salida(entrega: EntregaNotificacion) -> EntregaSalida:
    match = entrega.match
    e = explain(match)
    return EntregaSalida(
        id=entrega.id,
        canal=entrega.canal,
        estado=entrega.estado,
        fecha_intento=entrega.fecha_intento,
        read_at=entrega.read_at,
        created_at=entrega.created_at,
        documento_id=match.documento_id,
        suscripcion_id=match.suscripcion_id,
        texto_busqueda=match.suscripcion.texto_busqueda,
        titulo=match.documento.titulo,
        url_fuente=e.url,
        fecha=e.date,
        notice_number=e.notice_number,
        page=e.page,
        first_page=e.first_page,
        last_page=e.last_page,
        score=e.score,
        filtros=e.filters,
        excerpt=[ExcerptPart(text=p.text, match=p.match) for p in e.parts],
        shared_words=e.shared_words,
    )


def _propias(usuario: Usuario):
    """The deliveries of a user."""
    return (
        select(EntregaNotificacion)
        .join(EvaluacionMatch, EntregaNotificacion.match_id == EvaluacionMatch.id)
        .join(Suscripcion, EvaluacionMatch.suscripcion_id == Suscripcion.id)
        .where(Suscripcion.usuario_id == usuario.id)
    )


@router.get("/v1/notificaciones", response_model=list[EntregaSalida])
def listar_notificaciones(
    canal: Literal["bandeja", "correo"] | None = Query(None),
    unread: bool = Query(False),
    before: int | None = Query(None, description="Only the ones older than this id, for the next page"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    usuario: Usuario = Depends(get_usuario_actual),
    session: Session = Depends(get_session),
) -> list[EntregaSalida]:
    stmt = _propias(usuario)
    if canal is not None:
        stmt = stmt.where(EntregaNotificacion.canal == canal)
    if unread:
        stmt = stmt.where(EntregaNotificacion.read_at.is_(None), EntregaNotificacion.canal == "bandeja")
    if before is not None:
        stmt = stmt.where(EntregaNotificacion.id < before)
    match = joinedload(EntregaNotificacion.match)
    entregas = session.scalars(
        stmt.options(
            match.joinedload(EvaluacionMatch.documento),
            match.joinedload(EvaluacionMatch.fragmento),
            match.joinedload(EvaluacionMatch.suscripcion).defer(Suscripcion.embedding),
        )
        .order_by(EntregaNotificacion.id.desc())
        .limit(limit)
    ).all()
    return [_salida(entrega) for entrega in entregas]


@router.get("/v1/notificaciones/unread-count")
def contar_sin_leer(
    usuario: Usuario = Depends(get_usuario_actual), session: Session = Depends(get_session)
) -> dict[str, int]:
    unread = _propias(usuario).where(EntregaNotificacion.canal == "bandeja", EntregaNotificacion.read_at.is_(None))
    return {"unread": session.scalar(select(func.count()).select_from(unread.subquery()))}


@router.post("/v1/notificaciones/read")
def marcar_todas_leidas(
    usuario: Usuario = Depends(get_usuario_actual), session: Session = Depends(get_session)
) -> dict[str, int]:
    unread = _propias(usuario).where(EntregaNotificacion.canal == "bandeja", EntregaNotificacion.read_at.is_(None))
    result = session.execute(
        update(EntregaNotificacion)
        .where(EntregaNotificacion.id.in_(unread.with_only_columns(EntregaNotificacion.id)))
        .values(read_at=func.now())
        .execution_options(synchronize_session=False)
    )
    session.expire_all()
    return {"read": result.rowcount}


@router.post("/v1/notificaciones/{entrega_id}/read", response_model=EntregaSalida)
def marcar_leida(
    entrega_id: int, usuario: Usuario = Depends(get_usuario_actual), session: Session = Depends(get_session)
) -> EntregaSalida:
    entrega = session.scalar(_propias(usuario).where(EntregaNotificacion.id == entrega_id))
    if entrega is None:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    if entrega.read_at is None:
        entrega.read_at = datetime.datetime.now(datetime.UTC)
        session.flush()
    return _salida(entrega)
