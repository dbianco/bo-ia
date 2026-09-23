"""Sesiones respaldadas por tabla (FR-003, FR-004) — no JWT. El token es
opaco; toda la validación (existencia, expiración) pasa por `sesiones`,
así que cerrar sesión invalida de verdad, no solo del lado del cliente.
"""
from __future__ import annotations

import datetime
import secrets

from sqlalchemy.orm import Session

from src.db.models import Sesion, Usuario

DURACION_SESION = datetime.timedelta(days=14)


def _ahora() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def crear_sesion(session: Session, usuario: Usuario) -> Sesion:
    sesion = Sesion(
        token=secrets.token_urlsafe(32),
        usuario_id=usuario.id,
        expira_en=_ahora() + DURACION_SESION,
    )
    session.add(sesion)
    session.flush()
    return sesion


def obtener_usuario_de_sesion(session: Session, token: str) -> Usuario | None:
    sesion = session.get(Sesion, token)
    if sesion is None:
        return None
    if sesion.expira_en <= _ahora():
        return None
    return sesion.usuario


def invalidar_sesion(session: Session, token: str) -> None:
    sesion = session.get(Sesion, token)
    if sesion is not None:
        session.delete(sesion)
        session.flush()
