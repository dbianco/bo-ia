"""T010: `aplicar_filtros` — selección, rango numérico, clave no
declarada (FR-009, FR-012, FR-013)."""
import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.installation import FiltroRangoNumerico, FiltroSeleccion
from src.db.models import Documento, Fuente
from src.search.filters import FiltroNoDeclarado, ValorDeFiltroInvalido, aplicar_filtros

FILTROS_DECLARADOS = [
    FiltroSeleccion(clave="municipio", etiqueta="Municipio"),
    FiltroRangoNumerico(clave="presupuesto_estimado", etiqueta="Presupuesto estimado"),
]


def _crear_documento(session: Session, *, identificador: str, metadata: dict) -> Documento:
    fuente = session.scalar(select(Fuente).where(Fuente.clave == "test"))
    if fuente is None:
        fuente = Fuente(clave="test", nombre="test", config={})
        session.add(fuente)
        session.flush()
    documento = Documento(
        fuente_id=fuente.id,
        identificador_externo=identificador,
        fecha=datetime.date(2026, 1, 1),
        texto="texto",
        url_fuente=f"https://example.org/{identificador}",
        hash_contenido=f"hash-{identificador}",
        estado="completo",
        metadata_=metadata,
    )
    session.add(documento)
    session.flush()
    return documento


def test_filtro_seleccion_incluye_solo_el_valor_pedido(db_session: Session) -> None:
    _crear_documento(db_session, identificador="cp", metadata={"municipio": "Carlos Paz"})
    _crear_documento(db_session, identificador="no", metadata={"municipio": "Noetinger"})

    stmt = aplicar_filtros(select(Documento), {"municipio": "Carlos Paz"}, FILTROS_DECLARADOS)
    resultados = db_session.scalars(stmt).all()

    assert [d.identificador_externo for d in resultados] == ["cp"]


def test_filtro_rango_numerico_aplica_minimo_y_maximo(db_session: Session) -> None:
    _crear_documento(db_session, identificador="bajo", metadata={"presupuesto_estimado": 50_000})
    _crear_documento(db_session, identificador="medio", metadata={"presupuesto_estimado": 150_000})
    _crear_documento(db_session, identificador="alto", metadata={"presupuesto_estimado": 900_000})

    stmt = aplicar_filtros(
        select(Documento), {"presupuesto_estimado": "100000,500000"}, FILTROS_DECLARADOS
    )
    resultados = db_session.scalars(stmt).all()

    assert [d.identificador_externo for d in resultados] == ["medio"]


def test_filtro_rango_numerico_con_solo_minimo(db_session: Session) -> None:
    _crear_documento(db_session, identificador="bajo", metadata={"presupuesto_estimado": 50_000})
    _crear_documento(db_session, identificador="alto", metadata={"presupuesto_estimado": 900_000})

    stmt = aplicar_filtros(select(Documento), {"presupuesto_estimado": "100000,"}, FILTROS_DECLARADOS)
    resultados = db_session.scalars(stmt).all()

    assert [d.identificador_externo for d in resultados] == ["alto"]


def test_filtro_rango_numerico_con_valor_no_numerico_es_invalido(db_session: Session) -> None:
    with pytest.raises(ValorDeFiltroInvalido):
        aplicar_filtros(select(Documento), {"presupuesto_estimado": "no-numerico,"}, FILTROS_DECLARADOS)


def test_filtro_no_declarado_es_rechazado(db_session: Session) -> None:
    with pytest.raises(FiltroNoDeclarado):
        aplicar_filtros(select(Documento), {"clave_inventada": "x"}, FILTROS_DECLARADOS)
