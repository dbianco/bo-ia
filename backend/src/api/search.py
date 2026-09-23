"""Endpoint de búsqueda: GET /v1/search.

Búsqueda semántica con umbral (modo SEMANTIC, default). Los modos HYBRID y
ALL combinan la similitud vectorial con coincidencias de texto exacto
(búsqueda de texto completo en español sobre `fragmentos.texto_tsv`).

Etapa 1: además de fecha, acepta `filtro.<clave>` para cualquier filtro
declarado en `installation.yaml` (FR-009, FR-011, FR-012), traducido a SQL
por `aplicar_filtros` sobre `documentos.metadata`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_installation_config, get_session
from src.config.installation import InstallationConfig
from src.db.models import Documento, Fragmento
from src.processor.embeddings import EmbeddingProvider
from src.processor.hybrid import fusionar_rrf
from src.processor.threshold import filtrar_por_umbral, umbral_configurado
from src.search.filters import FiltroNoDeclarado, ValorDeFiltroInvalido, aplicar_filtros

router = APIRouter()

# Se trae más candidatos de los pedidos, se filtra por umbral en Python
# y recién ahí se corta al límite pedido: así el umbral se aplica antes
# que el límite, sin duplicar la lógica de threshold.py en SQL.
CANDIDATOS_MINIMOS = 50
FACTOR_SOBRE_MUESTREO = 5

PREFIJO_FILTRO = "filtro."


class ModoBusqueda(StrEnum):
    semantic = "semantic"
    hybrid = "hybrid"
    all = "all"


@dataclass
class ResultadoBusqueda:
    fragmento_id: int
    documento_id: int
    identificador_externo: str
    texto: str
    fecha: date
    url_fuente: str
    similitud: float
    coincidencia_texto: bool = field(default=False)


def _query_base(
    fecha_desde: date | None,
    fecha_hasta: date | None,
    filtros_solicitados: dict[str, str],
    filtros_declarados: list,
):
    stmt = select(Fragmento, Documento).join(Documento, Fragmento.documento_id == Documento.id)
    if fecha_desde is not None:
        stmt = stmt.where(Fragmento.fecha >= fecha_desde)
    if fecha_hasta is not None:
        stmt = stmt.where(Fragmento.fecha <= fecha_hasta)
    if filtros_solicitados:
        stmt = aplicar_filtros(stmt, filtros_solicitados, filtros_declarados)
    return stmt


def _candidatos_vectoriales(
    session: Session,
    embedder: EmbeddingProvider,
    consulta: str,
    fecha_desde: date | None,
    fecha_hasta: date | None,
    filtros_solicitados: dict[str, str],
    filtros_declarados: list,
    candidatos: int,
) -> dict[int, tuple[Fragmento, Documento, float]]:
    vector_consulta = embedder.embed_query(consulta)
    distancia = Fragmento.embedding.cosine_distance(vector_consulta)
    stmt = (
        _query_base(fecha_desde, fecha_hasta, filtros_solicitados, filtros_declarados)
        .add_columns(distancia.label("distancia"))
        .where(Fragmento.embedding.is_not(None))
        .order_by(distancia.asc())
        .limit(candidatos)
    )
    filas = session.execute(stmt).all()
    return {fragmento.id: (fragmento, documento, 1.0 - dist) for fragmento, documento, dist in filas}


def _candidatos_textuales(
    session: Session,
    consulta: str,
    fecha_desde: date | None,
    fecha_hasta: date | None,
    filtros_solicitados: dict[str, str],
    filtros_declarados: list,
    candidatos: int,
) -> dict[int, tuple[Fragmento, Documento, float]]:
    tsquery = func.plainto_tsquery("spanish", consulta)
    rank = func.ts_rank(Fragmento.texto_tsv, tsquery)
    stmt = (
        _query_base(fecha_desde, fecha_hasta, filtros_solicitados, filtros_declarados)
        .add_columns(rank.label("rank"))
        .where(Fragmento.texto_tsv.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(candidatos)
    )
    filas = session.execute(stmt).all()
    return {fragmento.id: (fragmento, documento, r) for fragmento, documento, r in filas}


def _resultado_desde(
    fid: int, fragmento: Fragmento, documento: Documento, similitud: float, coincidencia_texto: bool
) -> ResultadoBusqueda:
    return ResultadoBusqueda(
        fragmento_id=fid,
        documento_id=documento.id,
        identificador_externo=documento.identificador_externo,
        texto=fragmento.texto,
        fecha=fragmento.fecha,
        url_fuente=documento.url_fuente,
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
    filtros_solicitados: dict[str, str] | None = None,
    filtros_declarados: list | None = None,
) -> list[ResultadoBusqueda]:
    filtros_solicitados = filtros_solicitados or {}
    filtros_declarados = filtros_declarados or []
    candidatos = max(limite * FACTOR_SOBRE_MUESTREO, CANDIDATOS_MINIMOS)
    vectoriales = _candidatos_vectoriales(
        session, embedder, consulta, fecha_desde, fecha_hasta, filtros_solicitados, filtros_declarados, candidatos
    )

    if modo is ModoBusqueda.semantic:
        resultados = [
            _resultado_desde(fid, fragmento, documento, similitud, coincidencia_texto=False)
            for fid, (fragmento, documento, similitud) in vectoriales.items()
        ]
        resultados.sort(key=lambda r: r.similitud, reverse=True)
        return filtrar_por_umbral(resultados)[:limite]

    # HYBRID y ALL combinan candidatos vectoriales y textuales por RRF.
    textuales = _candidatos_textuales(
        session, consulta, fecha_desde, fecha_hasta, filtros_solicitados, filtros_declarados, candidatos
    )
    orden_vectorial = sorted(vectoriales, key=lambda fid: -vectoriales[fid][2])
    orden_textual = sorted(textuales, key=lambda fid: -textuales[fid][2])
    scores_rrf = fusionar_rrf(orden_vectorial, orden_textual)

    umbral = umbral_configurado()
    resultados = []
    for fid in scores_rrf:
        en_textual = fid in textuales
        en_vectorial = fid in vectoriales
        similitud = vectoriales[fid][2] if en_vectorial else 0.0
        fragmento, documento = vectoriales[fid][:2] if en_vectorial else textuales[fid][:2]

        if modo is ModoBusqueda.hybrid and not en_textual and similitud < umbral:
            # Sin coincidencia de texto que lo rescate, HYBRID exige el
            # mismo umbral que SEMANTIC.
            continue
        # ALL no filtra nada: unión completa, sin umbral.

        resultados.append(_resultado_desde(fid, fragmento, documento, similitud, en_textual))

    resultados.sort(key=lambda r: scores_rrf[r.fragmento_id], reverse=True)
    return resultados[:limite]


@router.get("/v1/search")
def buscar_endpoint(
    request: Request,
    q: str = Query(..., min_length=1, description="Consulta en lenguaje natural"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    mode: ModoBusqueda = Query(ModoBusqueda.semantic),
    session: Session = Depends(get_session),
    embedder: EmbeddingProvider = Depends(get_embedder),
    installation: InstallationConfig = Depends(get_installation_config),
) -> dict:
    filtros_solicitados = {
        clave.removeprefix(PREFIJO_FILTRO): valor
        for clave, valor in request.query_params.items()
        if clave.startswith(PREFIJO_FILTRO)
    }
    try:
        resultados = buscar(
            session,
            embedder,
            consulta=q,
            fecha_desde=date_from,
            fecha_hasta=date_to,
            limite=limit,
            modo=mode,
            filtros_solicitados=filtros_solicitados,
            filtros_declarados=installation.filtros,
        )
    except FiltroNoDeclarado as exc:
        raise HTTPException(status_code=422, detail=f"Filtro no declarado: {exc}") from exc
    except ValorDeFiltroInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "modo": mode.value,
        "resultados": [
            {
                "fragmento_id": r.fragmento_id,
                "documento_id": r.documento_id,
                "identificador_externo": r.identificador_externo,
                "texto": r.texto,
                "fecha": r.fecha.isoformat(),
                "url_fuente": r.url_fuente,
                "similitud": r.similitud,
                "coincidencia_texto": r.coincidencia_texto,
            }
            for r in resultados
        ],
        "total": len(resultados),
    }
