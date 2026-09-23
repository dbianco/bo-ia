"""T010: POST /v1/auth/registro, /login, /logout (FR-001 a FR-004,
SC-001, SC-002)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import COOKIE_SESION, get_session
from src.api.main import app
from src.db.models import Sesion, Usuario

REGISTRO_JSON = {"email": "cliente@example.org", "password": "una-contraseña-larga"}


@pytest.fixture()
def client(db_session: Session):
    def _get_session_override():
        yield db_session

    app.dependency_overrides[get_session] = _get_session_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_registro_crea_una_cuenta(client: TestClient, db_session: Session) -> None:
    respuesta = client.post("/v1/auth/registro", json=REGISTRO_JSON)

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["email"] == REGISTRO_JSON["email"]

    usuario = db_session.scalar(select(Usuario).where(Usuario.email == REGISTRO_JSON["email"]))
    assert usuario is not None
    assert usuario.password_hash != REGISTRO_JSON["password"]


def test_registro_con_email_duplicado_devuelve_409(client: TestClient, db_session: Session) -> None:
    client.post("/v1/auth/registro", json=REGISTRO_JSON)

    respuesta = client.post("/v1/auth/registro", json=REGISTRO_JSON)

    assert respuesta.status_code == 409
    assert db_session.query(Usuario).filter_by(email=REGISTRO_JSON["email"]).count() == 1


def test_login_con_credenciales_correctas_setea_cookie_de_sesion(
    client: TestClient, db_session: Session
) -> None:
    client.post("/v1/auth/registro", json=REGISTRO_JSON)

    respuesta = client.post("/v1/auth/login", json=REGISTRO_JSON)

    assert respuesta.status_code == 200
    assert COOKIE_SESION in respuesta.cookies
    assert db_session.query(Sesion).count() == 1


def test_login_con_contrasena_incorrecta_devuelve_401_sin_crear_sesion(
    client: TestClient, db_session: Session
) -> None:
    client.post("/v1/auth/registro", json=REGISTRO_JSON)

    respuesta = client.post(
        "/v1/auth/login", json={"email": REGISTRO_JSON["email"], "password": "incorrecta"}
    )

    assert respuesta.status_code == 401
    assert db_session.query(Sesion).count() == 0


def test_login_con_email_inexistente_devuelve_401(client: TestClient) -> None:
    respuesta = client.post(
        "/v1/auth/login", json={"email": "no-existe@example.org", "password": "cualquiera"}
    )
    assert respuesta.status_code == 401


def test_logout_invalida_la_sesion(client: TestClient, db_session: Session) -> None:
    client.post("/v1/auth/registro", json=REGISTRO_JSON)
    client.post("/v1/auth/login", json=REGISTRO_JSON)
    assert db_session.query(Sesion).count() == 1

    respuesta = client.post("/v1/auth/logout")

    assert respuesta.status_code == 204
    assert db_session.query(Sesion).count() == 0
