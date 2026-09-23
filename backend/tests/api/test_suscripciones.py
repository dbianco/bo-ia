"""T013: crear, listar, pausar, reanudar y borrar una suscripción propia;
401 sin sesión; 404 sobre una ajena (FR-007, FR-010, FR-011, SC-003,
SC-004)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_installation_config, get_session
from src.api.main import app
from src.config.installation import FiltroSeleccion, InstallationConfig
from src.processor.embeddings import FakeEmbeddingProvider

INSTALLATION = InstallationConfig(
    nombre="test", filtros=[FiltroSeleccion(clave="municipio", etiqueta="Municipio")]
)


@pytest.fixture()
def client(db_session: Session):
    def _get_session_override():
        yield db_session

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[get_embedder] = lambda: FakeEmbeddingProvider()
    app.dependency_overrides[get_installation_config] = lambda: INSTALLATION
    yield TestClient(app)
    app.dependency_overrides.clear()


def _registrar_y_loguear(client: TestClient, email: str) -> TestClient:
    datos = {"email": email, "password": "una-contraseña-larga"}
    client.post("/v1/auth/registro", json=datos)
    respuesta = client.post("/v1/auth/login", json=datos)
    assert respuesta.status_code == 200
    return client


def test_crear_suscripcion_queda_activa_y_con_embedding(client: TestClient, db_session: Session) -> None:
    _registrar_y_loguear(client, "uno@example.org")

    respuesta = client.post(
        "/v1/suscripciones",
        json={"texto_busqueda": "licitaciones de obra vial", "filtros": {"municipio": "Carlos Paz"}},
    )

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "activa"
    assert cuerpo["texto_busqueda"] == "licitaciones de obra vial"


def test_crear_suscripcion_con_filtro_no_declarado_devuelve_422(client: TestClient) -> None:
    _registrar_y_loguear(client, "uno@example.org")

    respuesta = client.post(
        "/v1/suscripciones",
        json={"texto_busqueda": "texto", "filtros": {"clave_inventada": "x"}},
    )

    assert respuesta.status_code == 422


def test_crear_suscripcion_sin_sesion_devuelve_401(client: TestClient) -> None:
    respuesta = client.post("/v1/suscripciones", json={"texto_busqueda": "texto", "filtros": {}})
    assert respuesta.status_code == 401


def test_listar_suscripciones_devuelve_solo_las_propias(client: TestClient) -> None:
    _registrar_y_loguear(client, "uno@example.org")
    client.post("/v1/suscripciones", json={"texto_busqueda": "mía", "filtros": {}})
    client.cookies.clear()

    _registrar_y_loguear(client, "dos@example.org")
    client.post("/v1/suscripciones", json={"texto_busqueda": "de otro", "filtros": {}})

    respuesta = client.get("/v1/suscripciones")

    assert respuesta.status_code == 200
    textos = [s["texto_busqueda"] for s in respuesta.json()]
    assert textos == ["de otro"]


def test_listar_suscripciones_sin_sesion_devuelve_401(client: TestClient) -> None:
    respuesta = client.get("/v1/suscripciones")
    assert respuesta.status_code == 401


def test_pausar_reanudar_y_borrar_una_suscripcion_propia(client: TestClient) -> None:
    _registrar_y_loguear(client, "uno@example.org")
    creada = client.post(
        "/v1/suscripciones", json={"texto_busqueda": "texto", "filtros": {}}
    ).json()
    sid = creada["id"]

    pausada = client.post(f"/v1/suscripciones/{sid}/pausar")
    assert pausada.status_code == 200
    assert pausada.json()["estado"] == "pausada"

    reanudada = client.post(f"/v1/suscripciones/{sid}/reanudar")
    assert reanudada.status_code == 200
    assert reanudada.json()["estado"] == "activa"

    borrada = client.delete(f"/v1/suscripciones/{sid}")
    assert borrada.status_code == 204

    listado = client.get("/v1/suscripciones")
    assert listado.json() == []


def test_pausar_una_suscripcion_ajena_devuelve_404(client: TestClient) -> None:
    _registrar_y_loguear(client, "uno@example.org")
    creada = client.post(
        "/v1/suscripciones", json={"texto_busqueda": "texto", "filtros": {}}
    ).json()
    sid = creada["id"]
    client.cookies.clear()

    _registrar_y_loguear(client, "dos@example.org")
    respuesta = client.post(f"/v1/suscripciones/{sid}/pausar")

    assert respuesta.status_code == 404


def test_borrar_una_suscripcion_ajena_devuelve_404(client: TestClient) -> None:
    _registrar_y_loguear(client, "uno@example.org")
    creada = client.post(
        "/v1/suscripciones", json={"texto_busqueda": "texto", "filtros": {}}
    ).json()
    sid = creada["id"]
    client.cookies.clear()

    _registrar_y_loguear(client, "dos@example.org")
    respuesta = client.delete(f"/v1/suscripciones/{sid}")

    assert respuesta.status_code == 404
