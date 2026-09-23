"""T016: `evaluar_documento` — match registrado, filtro que no matchea,
suscripción pausada, no duplica en re-evaluación (SC-006 a SC-009)."""
import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Documento, EvaluacionMatch, Fragmento, Fuente, Suscripcion, Usuario
from src.subscriptions.evaluator import evaluar_documento

DIM = 1024


def _one_hot(indice: int, dim: int = DIM) -> list[float]:
    v = [0.0] * dim
    v[indice] = 1.0
    return v


VECTOR_ALTO = _one_hot(0)  # similitud 1.0 contra sí mismo
VECTOR_BAJO = _one_hot(1)  # similitud 0.0 contra VECTOR_ALTO


@pytest.fixture()
def usuario(db_session: Session) -> Usuario:
    u = Usuario(email="cliente@example.org", password_hash="hash-de-prueba")
    db_session.add(u)
    db_session.flush()
    return u


def _crear_documento(
    session: Session, *, identificador: str = "doc-1", embedding: list[float] = VECTOR_ALTO, metadata: dict | None = None
) -> Documento:
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
        metadata_=metadata or {},
    )
    session.add(documento)
    session.flush()
    session.add(
        Fragmento(documento_id=documento.id, posicion=0, texto="texto", fecha=documento.fecha, embedding=embedding)
    )
    session.flush()
    return documento


def _crear_suscripcion(
    session: Session,
    usuario: Usuario,
    *,
    embedding: list[float] = VECTOR_ALTO,
    filtros: dict | None = None,
    estado: str = "activa",
) -> Suscripcion:
    suscripcion = Suscripcion(
        usuario_id=usuario.id,
        texto_busqueda="consulta de prueba",
        embedding=embedding,
        filtros=filtros or {},
        estado=estado,
    )
    session.add(suscripcion)
    session.flush()
    return suscripcion


def test_documento_que_matchea_registra_un_evaluacion_match(db_session: Session, usuario: Usuario) -> None:
    suscripcion = _crear_suscripcion(db_session, usuario, embedding=VECTOR_ALTO)
    documento = _crear_documento(db_session, embedding=VECTOR_ALTO)

    evaluar_documento(db_session, documento)

    matches = db_session.scalars(select(EvaluacionMatch)).all()
    assert len(matches) == 1
    assert matches[0].documento_id == documento.id
    assert matches[0].suscripcion_id == suscripcion.id
    assert matches[0].score >= 0.99
    assert matches[0].fecha_evaluacion is not None
    db_session.refresh(suscripcion)
    assert suscripcion.ultima_evaluacion is not None


def test_documento_que_no_matchea_semanticamente_no_registra_match(
    db_session: Session, usuario: Usuario
) -> None:
    _crear_suscripcion(db_session, usuario, embedding=VECTOR_ALTO)
    documento = _crear_documento(db_session, embedding=VECTOR_BAJO)

    evaluar_documento(db_session, documento)

    assert db_session.scalars(select(EvaluacionMatch)).all() == []


def test_documento_que_no_pasa_el_filtro_no_registra_match(db_session: Session, usuario: Usuario) -> None:
    _crear_suscripcion(
        db_session,
        usuario,
        embedding=VECTOR_ALTO,
        filtros={"municipio": {"tipo": "seleccion", "valor": "Carlos Paz"}},
    )
    documento = _crear_documento(db_session, embedding=VECTOR_ALTO, metadata={"municipio": "Noetinger"})

    evaluar_documento(db_session, documento)

    assert db_session.scalars(select(EvaluacionMatch)).all() == []


def test_suscripcion_pausada_no_se_evalua(db_session: Session, usuario: Usuario) -> None:
    suscripcion = _crear_suscripcion(db_session, usuario, embedding=VECTOR_ALTO, estado="pausada")
    documento = _crear_documento(db_session, embedding=VECTOR_ALTO)

    evaluar_documento(db_session, documento)

    assert db_session.scalars(select(EvaluacionMatch)).all() == []
    db_session.refresh(suscripcion)
    assert suscripcion.ultima_evaluacion is None


def test_reevaluar_el_mismo_documento_no_duplica_el_match(db_session: Session, usuario: Usuario) -> None:
    _crear_suscripcion(db_session, usuario, embedding=VECTOR_ALTO)
    documento = _crear_documento(db_session, embedding=VECTOR_ALTO)

    evaluar_documento(db_session, documento)
    evaluar_documento(db_session, documento)

    assert len(db_session.scalars(select(EvaluacionMatch)).all()) == 1
