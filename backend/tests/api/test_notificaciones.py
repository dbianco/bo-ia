"""T011: GET /v1/notificaciones — lista las propias, 401 sin sesión, no
ve las de otro usuario (FR-005, SC-004)."""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_installation_config, get_session
from src.api.main import app
from src.config.installation import InstallationConfig
from src.db.models import Documento, Fuente
from src.ingestor.contract import DocumentoNormalizado, ingerir_documento

INSTALLATION = InstallationConfig(nombre="test")


class _EmbedderFijo:
    """Devuelve el mismo vector para consulta y pasaje, para garantizar
    un match por encima del umbral sin depender del hash del texto."""

    def embed_query(self, texto: str) -> list[float]:
        return [1.0] + [0.0] * 1023

    def embed_passage(self, texto: str) -> list[float]:
        return [1.0] + [0.0] * 1023


@pytest.fixture()
def client(db_session: Session):
    def _get_session_override():
        yield db_session

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[get_embedder] = lambda: _EmbedderFijo()
    app.dependency_overrides[get_installation_config] = lambda: INSTALLATION
    yield TestClient(app)
    app.dependency_overrides.clear()


def _registrar_y_loguear(client: TestClient, email: str) -> None:
    datos = {"email": email, "password": "una-contraseña-larga"}
    client.post("/v1/auth/registro", json=datos)
    respuesta = client.post("/v1/auth/login", json=datos)
    assert respuesta.status_code == 200


def _ingerir_documento_que_matchea(db_session: Session) -> None:
    fuente = Fuente(clave="test", nombre="test", config={})
    db_session.add(fuente)
    db_session.flush()
    doc = DocumentoNormalizado(
        fuente_clave="test",
        identificador_externo="doc-1",
        fecha=datetime.date(2026, 1, 1),
        texto="texto de prueba",
        url_fuente="https://example.org/doc-1",
    )
    ingerir_documento(db_session, _EmbedderFijo(), doc)
    assert db_session.query(Documento).count() == 1


def test_listar_notificaciones_sin_sesion_devuelve_401(client: TestClient) -> None:
    respuesta = client.get("/v1/notificaciones")
    assert respuesta.status_code == 401


def test_listar_notificaciones_propias(client: TestClient, db_session: Session) -> None:
    _registrar_y_loguear(client, "uno@example.org")
    client.post("/v1/suscripciones", json={"texto_busqueda": "consulta", "filtros": {}})

    _ingerir_documento_que_matchea(db_session)

    respuesta = client.get("/v1/notificaciones")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert len(cuerpo) == 1
    assert cuerpo[0]["canal"] == "bandeja"
    assert cuerpo[0]["estado"] == "entregada"


def test_listar_notificaciones_no_ve_las_de_otro_usuario(client: TestClient, db_session: Session) -> None:
    _registrar_y_loguear(client, "uno@example.org")
    client.post("/v1/suscripciones", json={"texto_busqueda": "consulta", "filtros": {}})
    _ingerir_documento_que_matchea(db_session)
    client.cookies.clear()

    _registrar_y_loguear(client, "dos@example.org")
    respuesta = client.get("/v1/notificaciones")

    assert respuesta.status_code == 200
    assert respuesta.json() == []
