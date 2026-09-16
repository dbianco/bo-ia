"""Endpoint de búsqueda: GET /v1/search (FR-008 a FR-013, FR-015)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_session
from src.db.models import Boletin, Fragmento
from src.processor.embeddings import EmbeddingProvider
from src.processor.threshold import filtrar_por_umbral

router = APIRouter()

# Se trae más candidatos de los pedidos, se filtra por umbral en Python
# (FR-015) y recién ahí se corta al límite pedido (FR-013): así el umbral
# se aplica antes que el límite, como exige FR-015, sin duplicar la lógica
# de threshold.py en SQL.
CANDIDATOS_MINIMOS = 50
FACTOR_SOBRE_MUESTREO = 5


@dataclass
class ResultadoBusqueda:
    fragmento_id: int
    boletin_id: int
    identificador_oficial: str
    texto: str
    fecha_publicacion: date
    url_oficial: str
    similitud: float


def buscar(
    session: Session,
    embedder: EmbeddingProvider,
    *,
    consulta: str,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    limite: int = 10,
) -> list[ResultadoBusqueda]:
    vector_consulta = embedder.embed_query(consulta)
    distancia = Fragmento.embedding.cosine_distance(vector_consulta)

    stmt = (
        select(Fragmento, Boletin, distancia.label("distancia"))
        .join(Boletin, Fragmento.boletin_id == Boletin.id)
        .where(Fragmento.embedding.is_not(None))
    )
    if fecha_desde is not None:
        stmt = stmt.where(Fragmento.fecha_publicacion >= fecha_desde)
    if fecha_hasta is not None:
        stmt = stmt.where(Fragmento.fecha_publicacion <= fecha_hasta)

    candidatos = max(limite * FACTOR_SOBRE_MUESTREO, CANDIDATOS_MINIMOS)
    stmt = stmt.order_by(distancia.asc()).limit(candidatos)

    filas = session.execute(stmt).all()
    resultados = [
        ResultadoBusqueda(
            fragmento_id=fragmento.id,
            boletin_id=boletin.id,
            identificador_oficial=boletin.identificador_oficial,
            texto=fragmento.texto,
            fecha_publicacion=fragmento.fecha_publicacion,
            url_oficial=boletin.url_oficial,
            similitud=1.0 - dist,
        )
        for fragmento, boletin, dist in filas
    ]

    return filtrar_por_umbral(resultados)[:limite]


@router.get("/v1/search")
def buscar_endpoint(
    q: str = Query(..., min_length=1, description="Consulta en lenguaje natural"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session),
    embedder: EmbeddingProvider = Depends(get_embedder),
) -> dict:
    resultados = buscar(
        session, embedder, consulta=q, fecha_desde=date_from, fecha_hasta=date_to, limite=limit
    )
    return {
        "resultados": [
            {
                "fragmento_id": r.fragmento_id,
                "boletin_id": r.boletin_id,
                "identificador_oficial": r.identificador_oficial,
                "texto": r.texto,
                "fecha_publicacion": r.fecha_publicacion.isoformat(),
                "url_oficial": r.url_oficial,
                "similitud": round(r.similitud, 4),
            }
            for r in resultados
        ],
        "total": len(resultados),
    }
