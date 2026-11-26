"""Suscripciones: crear, listar, pausar, reanudar, borrar (FR-007 a
FR-011). Pausar/reanudar/borrar una suscripción ajena devuelve 404 (no
403), para no confirmarle a un tercero que el id existe (decisión de
`plan.md`)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_installation_config, get_session, get_usuario_actual
from src.config.installation import InstallationConfig
from src.db.models import CANALES_NOTIFICACION, Suscripcion, Usuario
from src.processor.embeddings import EmbeddingProvider
from src.search.filters import FiltroNoDeclarado, ValorDeFiltroInvalido, construir_filtros_suscripcion

router = APIRouter()


class SuscripcionEntrada(BaseModel):
    texto_busqueda: str = Field(min_length=1)
    filtros: dict[str, str] = Field(default_factory=dict)
    canales: list[str] = Field(default_factory=list)
    frecuencia_notificacion: Literal["immediate", "daily", "weekly"] = "immediate"


class SuscripcionCambio(BaseModel):
    """What is not said stays as it is."""

    canales: list[str] | None = Field(None, min_length=1)
    frecuencia_notificacion: Literal["immediate", "daily", "weekly"] | None = None


class SuscripcionSalida(BaseModel):
    id: int
    texto_busqueda: str
    filtros: dict
    estado: str
    canales: list[str]
    frecuencia_notificacion: str


def _salida(suscripcion: Suscripcion) -> SuscripcionSalida:
    return SuscripcionSalida(
        id=suscripcion.id,
        texto_busqueda=suscripcion.texto_busqueda,
        filtros=suscripcion.filtros,
        estado=suscripcion.estado,
        canales=suscripcion.canales,
        frecuencia_notificacion=suscripcion.frecuencia_notificacion,
    )


def _validar_canales(canales: list[str]) -> None:
    invalidos = set(canales) - set(CANALES_NOTIFICACION)
    if invalidos:
        raise HTTPException(status_code=422, detail=f"Canal no soportado: {', '.join(sorted(invalidos))}")


def _obtener_propia(session: Session, usuario: Usuario, suscripcion_id: int) -> Suscripcion:
    suscripcion = session.get(Suscripcion, suscripcion_id)
    if suscripcion is None or suscripcion.usuario_id != usuario.id:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")
    return suscripcion


@router.post("/v1/suscripciones", status_code=201, response_model=SuscripcionSalida)
def crear_suscripcion(
    entrada: SuscripcionEntrada,
    usuario: Usuario = Depends(get_usuario_actual),
    session: Session = Depends(get_session),
    embedder: EmbeddingProvider = Depends(get_embedder),
    installation: InstallationConfig = Depends(get_installation_config),
) -> SuscripcionSalida:
    try:
        filtros_snapshot = construir_filtros_suscripcion(entrada.filtros, installation.filtros)
    except FiltroNoDeclarado as exc:
        raise HTTPException(status_code=422, detail=f"Filtro no declarado: {exc}") from exc
    except ValorDeFiltroInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _validar_canales(entrada.canales)

    suscripcion = Suscripcion(
        usuario_id=usuario.id,
        texto_busqueda=entrada.texto_busqueda,
        embedding=embedder.embed_query(entrada.texto_busqueda),
        filtros=filtros_snapshot,
        estado="activa",
        canales=entrada.canales,
        frecuencia_notificacion=entrada.frecuencia_notificacion,
    )
    session.add(suscripcion)
    session.flush()
    return _salida(suscripcion)


@router.get("/v1/suscripciones", response_model=list[SuscripcionSalida])
def listar_suscripciones(
    usuario: Usuario = Depends(get_usuario_actual), session: Session = Depends(get_session)
) -> list[SuscripcionSalida]:
    suscripciones = session.scalars(
        select(Suscripcion).where(Suscripcion.usuario_id == usuario.id).order_by(Suscripcion.id)
    ).all()
    return [_salida(s) for s in suscripciones]


@router.patch("/v1/suscripciones/{suscripcion_id}", response_model=SuscripcionSalida)
def cambiar_suscripcion(
    suscripcion_id: int,
    cambio: SuscripcionCambio,
    usuario: Usuario = Depends(get_usuario_actual),
    session: Session = Depends(get_session),
) -> SuscripcionSalida:
    suscripcion = _obtener_propia(session, usuario, suscripcion_id)
    if cambio.canales is not None:
        _validar_canales(cambio.canales)
        suscripcion.canales = cambio.canales
    if cambio.frecuencia_notificacion is not None:
        suscripcion.frecuencia_notificacion = cambio.frecuencia_notificacion
    session.flush()
    return _salida(suscripcion)


@router.post("/v1/suscripciones/{suscripcion_id}/pausar", response_model=SuscripcionSalida)
def pausar_suscripcion(
    suscripcion_id: int,
    usuario: Usuario = Depends(get_usuario_actual),
    session: Session = Depends(get_session),
) -> SuscripcionSalida:
    suscripcion = _obtener_propia(session, usuario, suscripcion_id)
    suscripcion.estado = "pausada"
    session.flush()
    return _salida(suscripcion)


@router.post("/v1/suscripciones/{suscripcion_id}/reanudar", response_model=SuscripcionSalida)
def reanudar_suscripcion(
    suscripcion_id: int,
    usuario: Usuario = Depends(get_usuario_actual),
    session: Session = Depends(get_session),
) -> SuscripcionSalida:
    suscripcion = _obtener_propia(session, usuario, suscripcion_id)
    suscripcion.estado = "activa"
    session.flush()
    return _salida(suscripcion)


@router.delete("/v1/suscripciones/{suscripcion_id}", status_code=204)
def borrar_suscripcion(
    suscripcion_id: int,
    usuario: Usuario = Depends(get_usuario_actual),
    session: Session = Depends(get_session),
) -> None:
    suscripcion = _obtener_propia(session, usuario, suscripcion_id)
    session.delete(suscripcion)
    session.flush()
