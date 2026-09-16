"""Endpoint de valoraciones: POST /v1/valoraciones (FR-014)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.deps import get_session
from src.db.models import VALORES_FEEDBACK, Fragmento, Valoracion

router = APIRouter()


class ValoracionEntrada(BaseModel):
    fragmento_id: int
    consulta: str = Field(min_length=1)
    valor: str

    def validar_valor(self) -> None:
        if self.valor not in VALORES_FEEDBACK:
            raise ValueError(f"valor debe ser uno de {VALORES_FEEDBACK}")


class ValoracionSalida(BaseModel):
    id: int
    fragmento_id: int
    consulta: str
    valor: str


@router.post("/v1/valoraciones", status_code=201, response_model=ValoracionSalida)
def crear_valoracion(entrada: ValoracionEntrada, session: Session = Depends(get_session)) -> Valoracion:
    if entrada.valor not in VALORES_FEEDBACK:
        raise HTTPException(status_code=422, detail=f"valor debe ser uno de {VALORES_FEEDBACK}")

    fragmento = session.get(Fragmento, entrada.fragmento_id)
    if fragmento is None:
        raise HTTPException(status_code=404, detail="fragmento_id no existe")

    valoracion = Valoracion(fragmento_id=entrada.fragmento_id, consulta=entrada.consulta, valor=entrada.valor)
    session.add(valoracion)
    session.flush()
    return valoracion
