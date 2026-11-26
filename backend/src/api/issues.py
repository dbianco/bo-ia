"""The documents of one issue (one PDF of a gazette, for instance), together:
GET /v1/issues/{source}/{issue}. Public, like the search."""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_session
from src.db.models import SUPERSEDED, Documento, Fuente

router = APIRouter()


class IssueDocument(BaseModel):
    documento_id: int
    identificador_externo: str
    titulo: str | None
    notice_number: str | None
    first_page: int | None
    last_page: int | None
    url_fuente: str


class Issue(BaseModel):
    source: str
    issue: str
    fecha: datetime.date
    url_fuente: str
    documents: list[IssueDocument]


@router.get("/v1/issues/{source}/{issue}", response_model=Issue)
def get_issue(source: str, issue: str, session: Session = Depends(get_session)) -> Issue:
    documents = session.scalars(
        select(Documento)
        .join(Fuente, Documento.fuente_id == Fuente.id)
        .where(Fuente.clave == source, Documento.issue == issue, Documento.estado != SUPERSEDED)
        .order_by(Documento.id)  # ingested in the order in which they were printed
    ).all()
    if not documents:
        raise HTTPException(status_code=404, detail="Edición no encontrada")
    return Issue(
        source=source,
        issue=issue,
        fecha=documents[0].fecha,
        url_fuente=documents[0].url_fuente.partition("#")[0],
        documents=[
            IssueDocument(
                documento_id=d.id,
                identificador_externo=d.identificador_externo,
                titulo=d.titulo,
                notice_number=d.notice_number,
                first_page=d.first_page,
                last_page=d.last_page,
                url_fuente=d.url_fuente,
            )
            for d in documents
        ],
    )
