"""Endpoint de ingesta genérico: POST /v1/documentos (FR-001 a FR-003,
FR-006). Capa fina sobre `ingerir_documento` (`src/ingestor/contract.py`),
que hace todo el trabajo de persistencia, fragmentación y embeddings.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_session
from src.ingestor.contract import (
    DocumentoInvalido,
    DocumentoNormalizado,
    ErrorDeProcesamiento,
    ingerir_documento,
)
from src.processor.embeddings import EmbeddingProvider

router = APIRouter()


class DocumentoEntrada(BaseModel):
    fuente_clave: str
    identificador_externo: str
    fecha: date
    texto: str = Field(min_length=1)
    url_fuente: str
    titulo: str | None = None
    metadata: dict = Field(default_factory=dict)
    tamano_fragmento: int = 1000
    solapamiento_fragmento: int = 200


class DocumentoSalida(BaseModel):
    documento_id: int
    ya_existia: bool
    estado: str
    fragmentos_creados: int


@router.post("/v1/documentos", status_code=201, response_model=DocumentoSalida)
def ingerir_endpoint(
    entrada: DocumentoEntrada,
    session: Session = Depends(get_session),
    embedder: EmbeddingProvider = Depends(get_embedder),
) -> DocumentoSalida:
    doc = DocumentoNormalizado(
        fuente_clave=entrada.fuente_clave,
        identificador_externo=entrada.identificador_externo,
        fecha=entrada.fecha,
        texto=entrada.texto,
        url_fuente=entrada.url_fuente,
        titulo=entrada.titulo,
        metadata=entrada.metadata,
    )
    try:
        resultado = ingerir_documento(
            session,
            embedder,
            doc,
            tamano_fragmento=entrada.tamano_fragmento,
            solapamiento_fragmento=entrada.solapamiento_fragmento,
        )
    except DocumentoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ErrorDeProcesamiento as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return DocumentoSalida(
        documento_id=resultado.documento.id,
        ya_existia=resultado.ya_existia,
        estado=resultado.documento.estado,
        fragmentos_creados=resultado.fragmentos_creados,
    )
