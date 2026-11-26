"""Endpoint de búsqueda: GET /v1/search.

Búsqueda semántica con umbral (modo SEMANTIC, default). Los modos HYBRID y
ALL la combinan con coincidencias de texto. Además de fecha, acepta
`filtro.<clave>` para cualquier filtro declarado en `installation.yaml`
(FR-009, FR-011, FR-012).

Who answers, PostgreSQL or the in-process engine, is a setting
(`SEARCH_ENGINE`): the response does not change.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_installation_config, get_search_backend, get_session
from src.config.installation import InstallationConfig
from src.engine.backend import SearchBackend
from src.processor.embeddings import EmbeddingProvider
from src.search.filters import FiltroNoDeclarado, ValorDeFiltroInvalido
from src.search.postgres import buscar
from src.search.results import ModoBusqueda, ResultadoBusqueda

__all__ = ["ModoBusqueda", "ResultadoBusqueda", "buscar", "router"]

router = APIRouter()

PREFIJO_FILTRO = "filtro."


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
    backend: SearchBackend = Depends(get_search_backend),
) -> dict:
    filtros_solicitados = {
        clave.removeprefix(PREFIJO_FILTRO): valor
        for clave, valor in request.query_params.items()
        if clave.startswith(PREFIJO_FILTRO)
    }
    try:
        resultados = backend.search(
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
                "titulo": r.titulo,
                "notice_number": r.notice_number,
                "issue": r.issue,
                "segmented": r.segmented,
                "page": r.page,
                "first_page": r.first_page,
                "last_page": r.last_page,
            }
            for r in resultados
        ],
        "total": len(resultados),
    }
