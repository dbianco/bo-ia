"""Autenticación: registro, login, logout (FR-001 a FR-004).

Sesiones con cookie HttpOnly respaldadas por la tabla `sesiones` — no JWT
(decisión de `spec.md`). No usa `pydantic.EmailStr` a propósito: requiere
el paquete `email-validator`, que no es una dependencia del proyecto; un
patrón simple alcanza para esta primera versión.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import COOKIE_SESION, get_session
from src.auth.security import hash_password, verificar_password
from src.auth.sessions import crear_sesion, invalidar_sesion
from src.db.models import Usuario

router = APIRouter()

PATRON_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegistroEntrada(BaseModel):
    email: str = Field(pattern=PATRON_EMAIL)
    password: str = Field(min_length=8)


class LoginEntrada(BaseModel):
    email: str
    password: str


class UsuarioSalida(BaseModel):
    id: int
    email: str


@router.post("/v1/auth/registro", status_code=201, response_model=UsuarioSalida)
def registrar(entrada: RegistroEntrada, session: Session = Depends(get_session)) -> UsuarioSalida:
    existente = session.scalar(select(Usuario).where(Usuario.email == entrada.email))
    if existente is not None:
        raise HTTPException(status_code=409, detail="El email ya está registrado")

    usuario = Usuario(email=entrada.email, password_hash=hash_password(entrada.password))
    session.add(usuario)
    session.flush()
    return UsuarioSalida(id=usuario.id, email=usuario.email)


@router.post("/v1/auth/login", response_model=UsuarioSalida)
def iniciar_sesion(
    entrada: LoginEntrada, response: Response, session: Session = Depends(get_session)
) -> UsuarioSalida:
    usuario = session.scalar(select(Usuario).where(Usuario.email == entrada.email))
    if usuario is None or not verificar_password(entrada.password, usuario.password_hash):
        raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")

    sesion = crear_sesion(session, usuario)
    response.set_cookie(
        COOKIE_SESION,
        sesion.token,
        httponly=True,
        samesite="lax",
        expires=sesion.expira_en,
    )
    return UsuarioSalida(id=usuario.id, email=usuario.email)


@router.post("/v1/auth/logout", status_code=204)
def cerrar_sesion(
    request: Request, response: Response, session: Session = Depends(get_session)
) -> None:
    token = request.cookies.get(COOKIE_SESION)
    if token:
        invalidar_sesion(session, token)
    response.delete_cookie(COOKIE_SESION)
