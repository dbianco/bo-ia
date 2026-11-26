"""What a search returns, whichever implementation answers it."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from src.db.models import Documento, Fragmento


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
    titulo: str | None = None
    # Citation. `segmented` is None for a source whose documents are not parts
    # of an issue, and False for text of an issue that is in no notice.
    notice_number: str | None = None
    issue: str | None = None
    segmented: bool | None = None
    page: int | None = None  # of the fragment
    first_page: int | None = None  # of the document
    last_page: int | None = None


def resultado_desde(
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
        titulo=documento.titulo,
        notice_number=documento.notice_number,
        issue=documento.issue,
        segmented=None if documento.issue is None else documento.notice_number is not None,
        page=fragmento.page,
        first_page=documento.first_page,
        last_page=documento.last_page,
    )
