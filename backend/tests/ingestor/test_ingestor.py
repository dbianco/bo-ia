"""T012: validación de ingesta, idempotencia y conservación del contenido
original (FR-001, FR-002, FR-003, FR-006)."""
import datetime

import pytest
from sqlalchemy.orm import Session

from src.ingestor.ingest import BoletinInvalido, ingerir_boletin

BOLETIN_BASE = dict(
    jurisdiccion="cordoba",
    identificador_oficial="BO-2026-001",
    fecha_publicacion=datetime.date(2026, 9, 1),
    texto_original="Decreto 123/2026: ...",
    url_oficial="https://boletinoficial.cba.gov.ar/2026/BO-2026-001",
)


def test_ingerir_boletin_crea_registro_con_campos_obligatorios(db_session: Session) -> None:
    resultado = ingerir_boletin(db_session, **BOLETIN_BASE)

    assert resultado.ya_existia is False
    assert resultado.boletin.id is not None
    assert resultado.boletin.jurisdiccion == BOLETIN_BASE["jurisdiccion"]
    assert resultado.boletin.identificador_oficial == BOLETIN_BASE["identificador_oficial"]
    assert resultado.boletin.url_oficial == BOLETIN_BASE["url_oficial"]
    # FR-003: se conserva una referencia al contenido original recibido.
    assert resultado.boletin.texto_original == BOLETIN_BASE["texto_original"]


@pytest.mark.parametrize("campo_vacio", ["jurisdiccion", "identificador_oficial", "texto_original", "url_oficial"])
def test_ingerir_boletin_rechaza_campos_obligatorios_faltantes(db_session: Session, campo_vacio: str) -> None:
    datos = {**BOLETIN_BASE, campo_vacio: ""}
    with pytest.raises(BoletinInvalido):
        ingerir_boletin(db_session, **datos)


def test_ingerir_boletin_rechaza_fecha_publicacion_faltante(db_session: Session) -> None:
    datos = {**BOLETIN_BASE, "fecha_publicacion": None}
    with pytest.raises(BoletinInvalido):
        ingerir_boletin(db_session, **datos)


def test_ingerir_boletin_es_idempotente_por_identificador(db_session: Session) -> None:
    primero = ingerir_boletin(db_session, **BOLETIN_BASE)
    db_session.flush()
    segundo = ingerir_boletin(db_session, **BOLETIN_BASE)

    assert segundo.ya_existia is True
    assert segundo.boletin.id == primero.boletin.id


def test_ingerir_boletin_es_idempotente_por_hash_de_contenido(db_session: Session) -> None:
    primero = ingerir_boletin(db_session, **BOLETIN_BASE)
    db_session.flush()

    # Mismo texto, identificador oficial distinto: la idempotencia por hash
    # evita duplicar el mismo contenido bajo otro identificador.
    datos = {**BOLETIN_BASE, "identificador_oficial": "BO-2026-001-duplicado"}
    segundo = ingerir_boletin(db_session, **datos)

    assert segundo.ya_existia is True
    assert segundo.boletin.id == primero.boletin.id
