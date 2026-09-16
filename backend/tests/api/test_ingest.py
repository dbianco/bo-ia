"""T023: endpoint de ingesta — orquesta ingestor + fragmentador + embeddings
(FR-001 a FR-007)."""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_session
from src.api.main import app
from src.db.models import Boletin, Fragmento
from src.processor.embeddings import FakeEmbeddingProvider

BOLETIN_JSON = dict(
    jurisdiccion="cordoba",
    identificador_oficial="BO-ingest-1",
    fecha_publicacion="2026-02-01",
    texto_original="Decreto 456/2026: se aprueba el presupuesto anual de la provincia.",
    url_oficial="https://boletinoficial.cba.gov.ar/BO-ingest-1",
)


class _EmbedderQueSiempreFalla:
    def embed_query(self, texto: str) -> list[float]:
        raise RuntimeError("modelo no disponible")

    def embed_passage(self, texto: str) -> list[float]:
        raise RuntimeError("modelo no disponible")


@pytest.fixture()
def client(db_session: Session):
    def _get_session_override():
        yield db_session

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[get_embedder] = lambda: FakeEmbeddingProvider()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_ingerir_boletin_crea_fragmentos_con_embeddings(client: TestClient, db_session: Session) -> None:
    respuesta = client.post("/v1/boletines", json=BOLETIN_JSON)

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["ya_existia"] is False
    assert cuerpo["estado_ingesta"] == "completo"
    assert cuerpo["fragmentos_creados"] >= 1

    boletin = db_session.get(Boletin, cuerpo["boletin_id"])
    assert boletin is not None
    assert boletin.estado_ingesta == "completo"
    fragmentos = db_session.query(Fragmento).filter_by(boletin_id=boletin.id).all()
    assert len(fragmentos) == cuerpo["fragmentos_creados"]
    assert all(f.embedding is not None for f in fragmentos)
    assert all(f.fecha_publicacion == boletin.fecha_publicacion for f in fragmentos)


def test_ingerir_boletin_repetido_es_idempotente_y_no_duplica_fragmentos(
    client: TestClient, db_session: Session
) -> None:
    primera = client.post("/v1/boletines", json=BOLETIN_JSON)
    segunda = client.post("/v1/boletines", json=BOLETIN_JSON)

    assert segunda.status_code == 201
    assert segunda.json()["ya_existia"] is True
    assert segunda.json()["boletin_id"] == primera.json()["boletin_id"]
    assert segunda.json()["fragmentos_creados"] == primera.json()["fragmentos_creados"]


def test_ingerir_boletin_sin_campos_obligatorios_devuelve_422(client: TestClient) -> None:
    datos = {**BOLETIN_JSON, "url_oficial": ""}
    respuesta = client.post("/v1/boletines", json=datos)
    assert respuesta.status_code == 422


def test_error_de_procesamiento_no_pierde_el_boletin_ya_recibido(
    client: TestClient, db_session: Session
) -> None:
    """FR-006: un error de procesamiento (acá, el embedder falla) debe
    quedar registrado sin perder el documento recibido."""
    app.dependency_overrides[get_embedder] = lambda: _EmbedderQueSiempreFalla()

    respuesta = client.post(
        "/v1/boletines", json={**BOLETIN_JSON, "identificador_oficial": "BO-ingest-error"}
    )

    assert respuesta.status_code == 500

    boletin = (
        db_session.query(Boletin)
        .filter_by(jurisdiccion="cordoba", identificador_oficial="BO-ingest-error")
        .one_or_none()
    )
    assert boletin is not None, "el boletín no debe perderse aunque falle el procesamiento"
    assert boletin.estado_ingesta == "error"
    assert boletin.texto_original == BOLETIN_JSON["texto_original"]
