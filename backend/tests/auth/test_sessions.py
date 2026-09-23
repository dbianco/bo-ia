"""T006: `crear_sesion`/`obtener_usuario_de_sesion`/`invalidar_sesion`
(FR-003, FR-004)."""
import datetime

import pytest
from sqlalchemy.orm import Session

from src.auth.sessions import crear_sesion, invalidar_sesion, obtener_usuario_de_sesion
from src.db.models import Sesion, Usuario


@pytest.fixture()
def usuario(db_session: Session) -> Usuario:
    u = Usuario(email="cliente@example.org", password_hash="hash-de-prueba")
    db_session.add(u)
    db_session.flush()
    return u


def test_crear_sesion_devuelve_un_token_valido(db_session: Session, usuario: Usuario) -> None:
    sesion = crear_sesion(db_session, usuario)

    assert sesion.token
    assert sesion.usuario_id == usuario.id
    assert sesion.expira_en > datetime.datetime.now(datetime.UTC)


def test_obtener_usuario_de_sesion_con_token_valido(db_session: Session, usuario: Usuario) -> None:
    sesion = crear_sesion(db_session, usuario)

    encontrado = obtener_usuario_de_sesion(db_session, sesion.token)

    assert encontrado is not None
    assert encontrado.id == usuario.id


def test_obtener_usuario_de_sesion_con_token_inexistente(db_session: Session) -> None:
    assert obtener_usuario_de_sesion(db_session, "token-que-no-existe") is None


def test_obtener_usuario_de_sesion_con_token_expirado(db_session: Session, usuario: Usuario) -> None:
    sesion = crear_sesion(db_session, usuario)
    sesion.expira_en = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1)
    db_session.flush()

    assert obtener_usuario_de_sesion(db_session, sesion.token) is None


def test_invalidar_sesion_la_deja_inutilizable(db_session: Session, usuario: Usuario) -> None:
    sesion = crear_sesion(db_session, usuario)

    invalidar_sesion(db_session, sesion.token)

    assert obtener_usuario_de_sesion(db_session, sesion.token) is None
    assert db_session.get(Sesion, sesion.token) is None
