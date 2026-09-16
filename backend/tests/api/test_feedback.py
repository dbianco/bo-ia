"""T016: endpoint de valoraciones — pulgar arriba/abajo (FR-014)."""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_session
from src.api.main import app
from src.db.models import Boletin, Fragmento, Valoracion


@pytest.fixture()
def client(db_session: Session):
    def _get_session_override():
        yield db_session

    app.dependency_overrides[get_session] = _get_session_override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def fragmento(db_session: Session) -> Fragmento:
    boletin = Boletin(
        jurisdiccion="cordoba",
        identificador_oficial="BO-feedback-1",
        fecha_publicacion=datetime.date(2026, 1, 1),
        texto_original="texto",
        url_oficial="https://boletinoficial.cba.gov.ar/BO-feedback-1",
        hash_contenido="hash-feedback-1",
        estado_ingesta="completo",
    )
    db_session.add(boletin)
    db_session.flush()
    frag = Fragmento(boletin_id=boletin.id, posicion=0, texto="texto", fecha_publicacion=boletin.fecha_publicacion)
    db_session.add(frag)
    db_session.flush()
    return frag


def test_valorar_resultado_positivo_lo_asocia_a_consulta_y_fragmento(
    client: TestClient, db_session: Session, fragmento: Fragmento
) -> None:
    respuesta = client.post(
        "/v1/valoraciones",
        json={"fragmento_id": fragmento.id, "consulta": "decretos de presupuesto", "valor": "positivo"},
    )

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["fragmento_id"] == fragmento.id
    assert cuerpo["valor"] == "positivo"

    guardado = db_session.get(Valoracion, cuerpo["id"])
    assert guardado is not None
    assert guardado.consulta == "decretos de presupuesto"


def test_valorar_resultado_negativo(client: TestClient, fragmento: Fragmento) -> None:
    respuesta = client.post(
        "/v1/valoraciones", json={"fragmento_id": fragmento.id, "consulta": "x", "valor": "negativo"}
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["valor"] == "negativo"


def test_valorar_con_valor_invalido_devuelve_422(client: TestClient, fragmento: Fragmento) -> None:
    respuesta = client.post(
        "/v1/valoraciones", json={"fragmento_id": fragmento.id, "consulta": "x", "valor": "excelente"}
    )
    assert respuesta.status_code == 422


def test_valorar_fragmento_inexistente_devuelve_404(client: TestClient) -> None:
    respuesta = client.post(
        "/v1/valoraciones", json={"fragmento_id": 999999, "consulta": "x", "valor": "positivo"}
    )
    assert respuesta.status_code == 404
