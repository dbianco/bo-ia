"""T009: `ingerir_documento` — validación, idempotencia por fuente e
identificador y por hash, conservación del original ante fallo de
procesamiento (FR-002, FR-003, FR-006)."""
import datetime

import pytest
from sqlalchemy.orm import Session

from src.db.models import Documento
from src.ingestor.contract import (
    DocumentoInvalido,
    DocumentoNormalizado,
    ErrorDeProcesamiento,
    ingerir_documento,
)
from src.processor.embeddings import FakeEmbeddingProvider

DOC_BASE = dict(
    fuente_clave="cordoba-provincial",
    identificador_externo="BO-2026-001",
    fecha=datetime.date(2026, 9, 1),
    texto="Decreto 123/2026: ...",
    url_fuente="https://boletinoficial.cba.gov.ar/2026/BO-2026-001",
)


class _EmbedderQueSiempreFalla:
    def embed_query(self, texto: str) -> list[float]:
        raise RuntimeError("modelo no disponible")

    def embed_passage(self, texto: str) -> list[float]:
        raise RuntimeError("modelo no disponible")


def test_ingerir_documento_crea_registro_con_campos_obligatorios(db_session: Session) -> None:
    resultado = ingerir_documento(db_session, FakeEmbeddingProvider(), DocumentoNormalizado(**DOC_BASE))

    assert resultado.ya_existia is False
    assert resultado.documento.id is not None
    assert resultado.documento.identificador_externo == DOC_BASE["identificador_externo"]
    assert resultado.documento.url_fuente == DOC_BASE["url_fuente"]
    # FR-003: se conserva una referencia al contenido original recibido.
    assert resultado.documento.texto == DOC_BASE["texto"]
    assert resultado.documento.estado == "completo"
    assert resultado.fragmentos_creados >= 1
    assert resultado.documento.fuente.clave == DOC_BASE["fuente_clave"]


@pytest.mark.parametrize("campo_vacio", ["fuente_clave", "identificador_externo", "texto", "url_fuente"])
def test_ingerir_documento_rechaza_campos_obligatorios_faltantes(db_session: Session, campo_vacio: str) -> None:
    datos = {**DOC_BASE, campo_vacio: ""}
    with pytest.raises(DocumentoInvalido):
        ingerir_documento(db_session, FakeEmbeddingProvider(), DocumentoNormalizado(**datos))


def test_ingerir_documento_rechaza_fecha_faltante(db_session: Session) -> None:
    datos = {**DOC_BASE, "fecha": None}
    with pytest.raises(DocumentoInvalido):
        ingerir_documento(db_session, FakeEmbeddingProvider(), DocumentoNormalizado(**datos))


def test_ingerir_documento_es_idempotente_por_fuente_e_identificador(db_session: Session) -> None:
    primero = ingerir_documento(db_session, FakeEmbeddingProvider(), DocumentoNormalizado(**DOC_BASE))
    segundo = ingerir_documento(db_session, FakeEmbeddingProvider(), DocumentoNormalizado(**DOC_BASE))

    assert segundo.ya_existia is True
    assert segundo.documento.id == primero.documento.id
    assert segundo.fragmentos_creados == primero.fragmentos_creados


def test_ingerir_documento_es_idempotente_por_hash_de_contenido(db_session: Session) -> None:
    primero = ingerir_documento(db_session, FakeEmbeddingProvider(), DocumentoNormalizado(**DOC_BASE))

    # Mismo texto, identificador distinto: la idempotencia por hash evita
    # duplicar el mismo contenido bajo otro identificador.
    datos = {**DOC_BASE, "identificador_externo": "BO-2026-001-duplicado"}
    segundo = ingerir_documento(db_session, FakeEmbeddingProvider(), DocumentoNormalizado(**datos))

    assert segundo.ya_existia is True
    assert segundo.documento.id == primero.documento.id


def test_ingerir_documento_reusa_la_misma_fuente_entre_documentos(db_session: Session) -> None:
    primero = ingerir_documento(db_session, FakeEmbeddingProvider(), DocumentoNormalizado(**DOC_BASE))
    datos = {**DOC_BASE, "identificador_externo": "BO-2026-002", "texto": "otro texto"}
    segundo = ingerir_documento(db_session, FakeEmbeddingProvider(), DocumentoNormalizado(**datos))

    assert primero.documento.fuente_id == segundo.documento.fuente_id


def test_dos_fuentes_distintas_no_colisionan_con_el_mismo_identificador(db_session: Session) -> None:
    """FR-006 del design spec (SC-002): dos fuentes conviven sin
    colisionar aunque compartan `identificador_externo`. Cada una publica
    un texto propio (si el contenido fuera idéntico, la idempotencia por
    hash de contenido los trataría como el mismo documento — comportamiento
    heredado del MVP, no algo que este test deba ejercitar)."""
    uno = ingerir_documento(
        db_session,
        FakeEmbeddingProvider(),
        DocumentoNormalizado(**{**DOC_BASE, "fuente_clave": "fuente-a", "texto": "texto de la fuente A"}),
    )
    dos = ingerir_documento(
        db_session,
        FakeEmbeddingProvider(),
        DocumentoNormalizado(**{**DOC_BASE, "fuente_clave": "fuente-b", "texto": "texto de la fuente B"}),
    )

    assert dos.ya_existia is False
    assert uno.documento.id != dos.documento.id
    assert uno.documento.fuente_id != dos.documento.fuente_id


def test_error_de_procesamiento_no_pierde_el_documento_ya_recibido(db_session: Session) -> None:
    """FR-003/FR-006: un error de procesamiento (acá, el embedder falla)
    debe quedar registrado sin perder el documento recibido."""
    datos = {**DOC_BASE, "identificador_externo": "BO-error"}

    with pytest.raises(ErrorDeProcesamiento):
        ingerir_documento(db_session, _EmbedderQueSiempreFalla(), DocumentoNormalizado(**datos))

    documento = db_session.query(Documento).filter_by(identificador_externo="BO-error").one_or_none()
    assert documento is not None, "el documento no debe perderse aunque falle el procesamiento"
    assert documento.estado == "error"
    assert documento.texto == DOC_BASE["texto"]
