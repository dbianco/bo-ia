"""Endpoint de ingesta: POST /v1/boletines (FR-001 a FR-007).

Orquesta el ingestor (validación + persistencia idempotente del boletín)
y el fragmentador + embeddings. El boletín se commitea apenas se valida,
antes de intentar fragmentar: así, si la fragmentación o el embedding
fallan, el documento ya recibido no se pierde (FR-006) — solo queda
marcado con estado_ingesta="error", en su propio commit separado.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_session
from src.db.models import Fragmento
from src.ingestor.fragmenter import fragmentar_texto
from src.ingestor.ingest import BoletinInvalido, ingerir_boletin
from src.processor.embeddings import EmbeddingProvider

router = APIRouter()


class BoletinEntrada(BaseModel):
    jurisdiccion: str
    identificador_oficial: str
    fecha_publicacion: date
    texto_original: str = Field(min_length=1)
    url_oficial: str
    titulo: str | None = None
    tamano_fragmento: int = 1000
    solapamiento_fragmento: int = 200


class BoletinSalida(BaseModel):
    boletin_id: int
    ya_existia: bool
    estado_ingesta: str
    fragmentos_creados: int


@router.post("/v1/boletines", status_code=201, response_model=BoletinSalida)
def ingerir_endpoint(
    entrada: BoletinEntrada,
    session: Session = Depends(get_session),
    embedder: EmbeddingProvider = Depends(get_embedder),
) -> BoletinSalida:
    try:
        resultado = ingerir_boletin(
            session,
            jurisdiccion=entrada.jurisdiccion,
            identificador_oficial=entrada.identificador_oficial,
            fecha_publicacion=entrada.fecha_publicacion,
            texto_original=entrada.texto_original,
            url_oficial=entrada.url_oficial,
            titulo=entrada.titulo,
        )
    except BoletinInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    boletin = resultado.boletin
    # El boletín queda persistido ya, independiente de lo que pase después.
    session.commit()

    if resultado.ya_existia:
        fragmentos_existentes = session.query(Fragmento).filter_by(boletin_id=boletin.id).count()
        return BoletinSalida(
            boletin_id=boletin.id,
            ya_existia=True,
            estado_ingesta=boletin.estado_ingesta,
            fragmentos_creados=fragmentos_existentes,
        )

    try:
        textos = fragmentar_texto(
            entrada.texto_original,
            tamano=entrada.tamano_fragmento,
            solapamiento=entrada.solapamiento_fragmento,
        )
        if not textos:
            # No debería pasar (fragmentar_texto garantiza >=1 para texto no
            # vacío), pero FR-007 se verifica explícitamente igual.
            raise RuntimeError("La fragmentación no produjo ningún fragmento")

        for posicion, texto in enumerate(textos):
            embedding = embedder.embed_passage(texto)
            session.add(
                Fragmento(
                    boletin_id=boletin.id,
                    posicion=posicion,
                    texto=texto,
                    fecha_publicacion=boletin.fecha_publicacion,
                    embedding=embedding,
                )
            )
        boletin.estado_ingesta = "completo"
        session.commit()
    except Exception as exc:
        session.rollback()  # descarta fragmentos parcialmente insertados
        boletin.estado_ingesta = "error"
        session.commit()  # FR-006: el error queda registrado sin perder el boletín
        raise HTTPException(
            status_code=500,
            detail="Error al fragmentar o generar embeddings; el boletín quedó registrado con estado 'error'.",
        ) from exc

    return BoletinSalida(
        boletin_id=boletin.id,
        ya_existia=False,
        estado_ingesta=boletin.estado_ingesta,
        fragmentos_creados=len(textos),
    )
