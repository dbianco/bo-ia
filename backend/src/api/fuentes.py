"""Ejecución manual de un conector: POST /v1/fuentes/{clave}/ejecutar
(FR-011), para operabilidad y debugging sin esperar al scheduler."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_installation_config, get_session
from src.config.installation import InstallationConfig
from src.connectors.registry import CONECTORES, VERSIONES
from src.connectors.runner import ejecutar_conector
from src.db.models import Fuente
from src.processor.embeddings import EmbeddingProvider

router = APIRouter()


class EjecucionSalida(BaseModel):
    ejecucion_id: int
    estado: str
    descubiertos: int
    nuevos: int
    existentes: int
    errores: int


@router.post("/v1/fuentes/{clave}/ejecutar", response_model=EjecucionSalida)
def ejecutar_fuente(
    clave: str,
    session: Session = Depends(get_session),
    embedder: EmbeddingProvider = Depends(get_embedder),
    installation: InstallationConfig = Depends(get_installation_config),
) -> EjecucionSalida:
    fuente_cfg = next((f for f in installation.fuentes if f.clave == clave), None)
    if fuente_cfg is None or fuente_cfg.conector is None:
        raise HTTPException(
            status_code=404, detail=f"La fuente '{clave}' no existe o no tiene conector configurado"
        )

    fuente = session.scalar(select(Fuente).where(Fuente.clave == clave))
    if fuente is None:
        raise HTTPException(status_code=404, detail=f"La fuente '{clave}' no existe")

    conector_cls = CONECTORES[fuente_cfg.conector.tipo]
    version = VERSIONES.get(fuente_cfg.conector.tipo, fuente_cfg.conector.tipo)
    ejecucion = ejecutar_conector(
        session, embedder, fuente, conector_cls(), fuente_cfg.conector.config, version_conector=version
    )
    return EjecucionSalida(
        ejecucion_id=ejecucion.id,
        estado=ejecucion.estado,
        descubiertos=ejecucion.descubiertos,
        nuevos=ejecucion.nuevos,
        existentes=ejecucion.existentes,
        errores=ejecucion.errores,
    )
