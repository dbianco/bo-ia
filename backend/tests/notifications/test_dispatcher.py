"""T006: `crear_entregas_para_match` — canales por defecto/declarados,
"bandeja" inmediata, "correo" con SMTP mockeado, no duplica (FR-001 a
FR-004, FR-007, FR-008, SC-001, SC-002, SC-003, SC-005, SC-006)."""
import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Documento, EntregaNotificacion, EvaluacionMatch, Fuente, Suscripcion, Usuario
from src.notifications.dispatcher import crear_entregas_para_match
from src.notifications.email import EnvioCorreoFallido
from src.notifications.outbox import send_pending


@pytest.fixture()
def usuario(db_session: Session) -> Usuario:
    u = Usuario(email="cliente@example.org", password_hash="hash-de-prueba")
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture()
def match(db_session: Session, usuario: Usuario):
    def _crear(*, canales: list | None = None) -> EvaluacionMatch:
        fuente = db_session.scalar(select(Fuente).where(Fuente.clave == "test"))
        if fuente is None:
            fuente = Fuente(clave="test", nombre="test", config={})
            db_session.add(fuente)
            db_session.flush()
        documento = Documento(
            fuente_id=fuente.id,
            identificador_externo=f"doc-{id(canales)}",
            fecha=datetime.date(2026, 1, 1),
            texto="texto",
            url_fuente="https://example.org/doc",
            hash_contenido=f"hash-{id(canales)}",
            estado="completo",
        )
        db_session.add(documento)
        db_session.flush()

        suscripcion = Suscripcion(
            usuario_id=usuario.id,
            texto_busqueda="consulta",
            embedding=[0.0] * 1024,
            filtros={},
            estado="activa",
            canales=canales if canales is not None else [],
        )
        db_session.add(suscripcion)
        db_session.flush()

        m = EvaluacionMatch(
            documento_id=documento.id,
            suscripcion_id=suscripcion.id,
            score=0.9,
            filtros_aplicados={},
            fecha_evaluacion=datetime.datetime.now(datetime.UTC),
        )
        db_session.add(m)
        db_session.flush()
        m.suscripcion = suscripcion
        return m

    return _crear


def test_sin_canales_declarados_crea_una_entrega_bandeja(db_session: Session, match) -> None:
    m = match(canales=[])

    crear_entregas_para_match(db_session, m)

    entregas = db_session.scalars(select(EntregaNotificacion).where(EntregaNotificacion.match_id == m.id)).all()
    assert len(entregas) == 1
    assert entregas[0].canal == "bandeja"
    assert entregas[0].estado == "entregada"


def test_crear_entregas_no_llama_a_smtp(db_session: Session, match) -> None:
    """Plan 10: sending is of the outbox (test_outbox.py)."""
    m = match(canales=["bandeja", "correo"])

    with patch("src.notifications.outbox.enviar_correo") as enviar:
        crear_entregas_para_match(db_session, m)

    enviar.assert_not_called()


def test_dos_canales_declarados_crea_dos_entregas(db_session: Session, match) -> None:
    m = match(canales=["bandeja", "correo"])

    crear_entregas_para_match(db_session, m)

    entregas = db_session.scalars(select(EntregaNotificacion).where(EntregaNotificacion.match_id == m.id)).all()
    assert sorted((e.canal, e.estado) for e in entregas) == [("bandeja", "entregada"), ("correo", "pendiente")]


def _enviar(db_session: Session, settings) -> EntregaNotificacion:
    send_pending(db_session, settings)
    return db_session.scalars(select(EntregaNotificacion)).one()


def test_correo_exitoso_queda_entregada(db_session: Session, match, settings) -> None:
    crear_entregas_para_match(db_session, match(canales=["correo"]))

    with patch("src.notifications.outbox.enviar_correo") as enviar:
        entrega = _enviar(db_session, settings)

    enviar.assert_called_once()
    assert entrega.estado == "entregada"
    assert entrega.fecha_intento is not None


def test_correo_fallido_queda_pendiente_con_error_y_no_propaga(db_session: Session, match, settings) -> None:
    crear_entregas_para_match(db_session, match(canales=["correo"]))

    with patch("src.notifications.outbox.enviar_correo", side_effect=EnvioCorreoFallido("SMTP caído")):
        entrega = _enviar(db_session, settings)  # no debe lanzar

    assert entrega.estado == "pendiente"  # plan 10: it is tried again
    assert entrega.error_proveedor == "SMTP caído"


def test_error_inesperado_en_el_envio_tampoco_propaga(db_session: Session, match, settings) -> None:
    crear_entregas_para_match(db_session, match(canales=["correo"]))

    with patch("src.notifications.outbox.enviar_correo", side_effect=RuntimeError("bug inesperado")):
        entrega = _enviar(db_session, settings)

    assert entrega.estado == "pendiente" and entrega.error_proveedor == "bug inesperado"


def test_recrear_entregas_para_el_mismo_match_no_duplica(db_session: Session, match) -> None:
    m = match(canales=["bandeja"])

    crear_entregas_para_match(db_session, m)
    crear_entregas_para_match(db_session, m)

    entregas = db_session.scalars(select(EntregaNotificacion).where(EntregaNotificacion.match_id == m.id)).all()
    assert len(entregas) == 1
