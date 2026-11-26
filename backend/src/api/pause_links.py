"""Pausing a subscription with the signed link of an email, without signing in.

Looking at the link does not pause: mail scanners open links by themselves."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.deps import get_session
from src.db.models import Suscripcion
from src.notifications.links import read_pause_token
from src.notifications.settings import link_secret

router = APIRouter()


class PauseLink(BaseModel):
    token: str


class PauseLinkState(BaseModel):
    texto_busqueda: str
    estado: str


def _subscription(session: Session, token: str) -> Suscripcion:
    identifier = read_pause_token(link_secret(), token)
    subscription = session.get(Suscripcion, identifier) if identifier is not None else None
    if subscription is None:
        raise HTTPException(status_code=404, detail="El enlace no es válido o venció")
    return subscription


@router.get("/v1/pause-links", response_model=PauseLinkState)
def look_at_link(token: str = Query(...), session: Session = Depends(get_session)) -> PauseLinkState:
    subscription = _subscription(session, token)
    return PauseLinkState(texto_busqueda=subscription.texto_busqueda, estado=subscription.estado)


@router.post("/v1/pause-links", response_model=PauseLinkState)
def pause_with_link(link: PauseLink, session: Session = Depends(get_session)) -> PauseLinkState:
    subscription = _subscription(session, link.token)
    subscription.estado = "pausada"
    session.flush()
    return PauseLinkState(texto_busqueda=subscription.texto_busqueda, estado=subscription.estado)
