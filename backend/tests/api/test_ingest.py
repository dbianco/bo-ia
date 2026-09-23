"""Endpoint de ingesta genérico: POST /v1/documentos (FR-001 a FR-003,
FR-006)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_session
from src.api.main import app
from src.db.models import Documento, Fragmento
from src.processor.embeddings import FakeEmbeddingProvider

DOCUMENTO_JSON = dict(
    fuente_clave="cordoba-provincial",
    identificador_externo="BO-ingest-1",
    fecha="2026-02-01",
    texto="Decreto 456/2026: se aprueba el presupuesto anual de la provincia.",
    url_fuente="https://boletinoficial.cba.gov.ar/BO-ingest-1",
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


def test_ingerir_documento_crea_fragmentos_con_embeddings(client: TestClient, db_session: Session) -> None:
    respuesta = client.post("/v1/documentos", json=DOCUMENTO_JSON)

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["ya_existia"] is False
    assert cuerpo["estado"] == "completo"
    assert cuerpo["fragmentos_creados"] >= 1

    documento = db_session.get(Documento, cuerpo["documento_id"])
    assert documento is not None
    assert documento.estado == "completo"
    fragmentos = db_session.query(Fragmento).filter_by(documento_id=documento.id).all()
    assert len(fragmentos) == cuerpo["fragmentos_creados"]
    assert all(f.embedding is not None for f in fragmentos)
    assert all(f.fecha == documento.fecha for f in fragmentos)


def test_ingerir_documento_repetido_es_idempotente_y_no_duplica_fragmentos(
    client: TestClient, db_session: Session
) -> None:
    primera = client.post("/v1/documentos", json=DOCUMENTO_JSON)
    segunda = client.post("/v1/documentos", json=DOCUMENTO_JSON)

    assert segunda.status_code == 201
    assert segunda.json()["ya_existia"] is True
    assert segunda.json()["documento_id"] == primera.json()["documento_id"]
    assert segunda.json()["fragmentos_creados"] == primera.json()["fragmentos_creados"]


def test_ingerir_documento_sin_campos_obligatorios_devuelve_422(client: TestClient) -> None:
    datos = {**DOCUMENTO_JSON, "url_fuente": ""}
    respuesta = client.post("/v1/documentos", json=datos)
    assert respuesta.status_code == 422


def test_error_de_procesamiento_no_pierde_el_documento_ya_recibido(
    client: TestClient, db_session: Session
) -> None:
    """FR-003/FR-006: un error de procesamiento (acá, el embedder falla)
    debe quedar registrado sin perder el documento recibido."""
    app.dependency_overrides[get_embedder] = lambda: _EmbedderQueSiempreFalla()

    respuesta = client.post(
        "/v1/documentos", json={**DOCUMENTO_JSON, "identificador_externo": "BO-ingest-error"}
    )

    assert respuesta.status_code == 500

    documento = (
        db_session.query(Documento).filter_by(identificador_externo="BO-ingest-error").one_or_none()
    )
    assert documento is not None, "el documento no debe perderse aunque falle el procesamiento"
    assert documento.estado == "error"
    assert documento.texto == DOCUMENTO_JSON["texto"]
