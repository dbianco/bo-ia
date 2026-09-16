"""Endpoint de búsqueda: GET /v1/search.

FR-008 a FR-013, FR-015: búsqueda semántica con umbral (modo SEMANTIC,
default). FR-028 a FR-031: modos HYBRID y ALL, que combinan la similitud
vectorial con coincidencias de texto exacto (búsqueda de texto completo en
español sobre `fragmentos.texto_tsv`), agregados tras encontrar que
consultas de una sola palabra no siempre superan el umbral vectorial
aunque el término aparezca literalmente en el texto.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_session
from src.db.models import Boletin, Fragmento
from src.processor.embeddings import EmbeddingProvider
from src.processor.hybrid import fusionar_rrf
from src.processor.threshold import filtrar_por_umbral, umbral_configurado

router = APIRouter()

# Se trae más candidatos de los pedidos, se filtra por umbral en Python
# (FR-015) y recién ahí se corta al límite pedido (FR-013): así el umbral
# se aplica antes que el límite, sin duplicar la lógica de threshold.py en SQL.
CANDIDATOS_MINIMOS = 50
FACTOR_SOBRE_MUESTREO = 5


class ModoBusqueda(str, Enum):
    semantic = "semantic"
    hybrid = "hybrid"
    all = "all"


@dataclass
class ResultadoBusqueda:
    fragmento_id: int
    boletin_id: int
    identificador_oficial: str
    texto: str
    fecha_publicacion: date
    url_oficial: str
    similitud: float
    coincidencia_texto: bool = field(default=False)


def _query_base(fecha_desde: date | None, fecha_hasta: date | None):
    stmt = select(Fragmento, Boletin).join(Boletin, Fragmento.boletin_id == Boletin.id)
    if fecha_desde is not None:
        stmt = stmt.where(Fragmento.fecha_publicacion >= fecha_desde)
    if fecha_hasta is not None:
        stmt = stmt.where(Fragmento.fecha_publicacion <= fecha_hasta)
    return stmt


def _candidatos_vectoriales(
    session: Session,
    embedder: EmbeddingProvider,
    consulta: str,
    fecha_desde: date | None,
    fecha_hasta: date | None,
    candidatos: int,
) -> dict[int, tuple[Fragmento, Boletin, float]]:
    vector_consulta = embedder.embed_query(consulta)
    distancia = Fragmento.embedding.cosine_distance(vector_consulta)
    stmt = (
        _query_base(fecha_desde, fecha_hasta)
        .add_columns(distancia.label("distancia"))
        .where(Fragmento.embedding.is_not(None))
        .order_by(distancia.asc())
        .limit(candidatos)
    )
    filas = session.execute(stmt).all()
    return {fragmento.id: (fragmento, boletin, 1.0 - dist) for fragmento, boletin, dist in filas}


def _candidatos_textuales(
    session: Session,
    consulta: str,
    fecha_desde: date | None,
    fecha_hasta: date | None,
    candidatos: int,
) -> dict[int, tuple[Fragmento, Boletin, float]]:
    tsquery = func.plainto_tsquery("spanish", consulta)
    rank = func.ts_rank(Fragmento.texto_tsv, tsquery)
    stmt = (
        _query_base(fecha_desde, fecha_hasta)
        .add_columns(rank.label("rank"))
        .where(Fragmento.texto_tsv.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(candidatos)
    )
    filas = session.execute(stmt).all()
    return {fragmento.id: (fragmento, boletin, r) for fragmento, boletin, r in filas}


def _resultado_desde(fid: int, fragmento: Fragmento, boletin: Boletin, similitud: float, coincidencia_texto: bool) -> ResultadoBusqueda:
    return ResultadoBusqueda(
        fragmento_id=fid,
        boletin_id=boletin.id,
        identificador_oficial=boletin.identificador_oficial,
        texto=fragmento.texto,
        fecha_publicacion=fragmento.fecha_publicacion,
        url_oficial=boletin.url_oficial,
        similitud=round(similitud, 4),
        coincidencia_texto=coincidencia_texto,
    )


def buscar(
    session: Session,
    embedder: EmbeddingProvider,
    *,
    consulta: str,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    limite: int = 10,
    modo: ModoBusqueda = ModoBusqueda.semantic,
) -> list[ResultadoBusqueda]:
    candidatos = max(limite * FACTOR_SOBRE_MUESTREO, CANDIDATOS_MINIMOS)
    vectoriales = _candidatos_vectoriales(session, embedder, consulta, fecha_desde, fecha_hasta, candidatos)

    if modo is ModoBusqueda.semantic:
        resultados = [
            _resultado_desde(fid, fragmento, boletin, similitud, coincidencia_texto=False)
            for fid, (fragmento, boletin, similitud) in vectoriales.items()
        ]
        resultados.sort(key=lambda r: r.similitud, reverse=True)
        return filtrar_por_umbral(resultados)[:limite]

    # HYBRID y ALL combinan candidatos vectoriales y textuales por RRF.
    textuales = _candidatos_textuales(session, consulta, fecha_desde, fecha_hasta, candidatos)
    orden_vectorial = sorted(vectoriales, key=lambda fid: -vectoriales[fid][2])
    orden_textual = sorted(textuales, key=lambda fid: -textuales[fid][2])
    scores_rrf = fusionar_rrf(orden_vectorial, orden_textual)

    umbral = umbral_configurado()
    resultados = []
    for fid, rrf_score in scores_rrf.items():
        en_textual = fid in textuales
        en_vectorial = fid in vectoriales
        similitud = vectoriales[fid][2] if en_vectorial else 0.0
        fragmento, boletin = vectoriales[fid][:2] if en_vectorial else textuales[fid][:2]

        if modo is ModoBusqueda.hybrid and not en_textual and similitud < umbral:
            # Sin coincidencia de texto que lo rescate, HYBRID exige el
            # mismo umbral que SEMANTIC.
            continue
        # ALL no filtra nada: unión completa, sin umbral.

        resultados.append(_resultado_desde(fid, fragmento, boletin, similitud, en_textual))

    resultados.sort(key=lambda r: scores_rrf[r.fragmento_id], reverse=True)
    return resultados[:limite]


@router.get("/v1/search")
def buscar_endpoint(
    q: str = Query(..., min_length=1, description="Consulta en lenguaje natural"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    mode: ModoBusqueda = Query(ModoBusqueda.semantic),
    session: Session = Depends(get_session),
    embedder: EmbeddingProvider = Depends(get_embedder),
) -> dict:
    resultados = buscar(
        session,
        embedder,
        consulta=q,
        fecha_desde=date_from,
        fecha_hasta=date_to,
        limite=limit,
        modo=mode,
    )
    return {
        "modo": mode.value,
        "resultados": [
            {
                "fragmento_id": r.fragmento_id,
                "boletin_id": r.boletin_id,
                "identificador_oficial": r.identificador_oficial,
                "texto": r.texto,
                "fecha_publicacion": r.fecha_publicacion.isoformat(),
                "url_oficial": r.url_oficial,
                "similitud": r.similitud,
                "coincidencia_texto": r.coincidencia_texto,
            }
            for r in resultados
        ],
        "total": len(resultados),
    }
