"""T013: filtros declarados por instalación sobre GET /v1/search
(FR-011, SC-002, SC-005 del spec de la Etapa 1) — dos fuentes conviven en
la misma instalación, y un filtro selectivo excluye lo que no matchea."""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_installation_config, get_session
from src.api.main import app
from src.config.installation import FiltroSeleccion, InstallationConfig
from src.db.models import Documento, Fragmento, Fuente

DIM = 1024
VECTOR = [1.0] + [0.0] * (DIM - 1)


class _VectorFijoEmbeddingProvider:
    def embed_query(self, texto: str) -> list[float]:
        return VECTOR

    def embed_passage(self, texto: str) -> list[float]:
        return VECTOR


def _crear_documento(
    session: Session, *, fuente_clave: str, identificador: str, municipio: str
) -> Fragmento:
    fuente = session.query(Fuente).filter_by(clave=fuente_clave).one_or_none()
    if fuente is None:
        fuente = Fuente(clave=fuente_clave, nombre=fuente_clave, config={})
        session.add(fuente)
        session.flush()
    documento = Documento(
        fuente_id=fuente.id,
        identificador_externo=identificador,
        fecha=datetime.date(2026, 1, 1),
        texto="texto de prueba",
        url_fuente=f"https://example.org/{identificador}",
        hash_contenido=f"hash-{identificador}",
        estado="completo",
        metadata_={"provincia": "Córdoba", "municipio": municipio},
    )
    session.add(documento)
    session.flush()
    fragmento = Fragmento(
        documento_id=documento.id, posicion=0, texto="texto de prueba", fecha=documento.fecha, embedding=VECTOR
    )
    session.add(fragmento)
    session.flush()
    return fragmento


@pytest.fixture()
def client(db_session: Session):
    installation = InstallationConfig(
        nombre="Boletines Córdoba",
        filtros=[FiltroSeleccion(clave="municipio", etiqueta="Municipio")],
    )

    def _get_session_override():
        yield db_session

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[get_embedder] = lambda: _VectorFijoEmbeddingProvider()
    app.dependency_overrides[get_installation_config] = lambda: installation
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_dos_fuentes_conviven_en_busqueda_sin_filtro(client: TestClient, db_session: Session) -> None:
    _crear_documento(db_session, fuente_clave="carlos-paz-municipal", identificador="cp-1", municipio="Carlos Paz")
    _crear_documento(db_session, fuente_clave="noetinger-municipal", identificador="no-1", municipio="Noetinger")

    respuesta = client.get("/v1/search", params={"q": "texto de prueba", "mode": "all"})

    identificadores = {r["identificador_externo"] for r in respuesta.json()["resultados"]}
    assert identificadores == {"cp-1", "no-1"}


def test_filtro_municipio_carlos_paz_excluye_noetinger(client: TestClient, db_session: Session) -> None:
    _crear_documento(db_session, fuente_clave="carlos-paz-municipal", identificador="cp-1", municipio="Carlos Paz")
    _crear_documento(db_session, fuente_clave="noetinger-municipal", identificador="no-1", municipio="Noetinger")

    respuesta = client.get(
        "/v1/search", params={"q": "texto de prueba", "mode": "all", "filtro.municipio": "Carlos Paz"}
    )
    cuerpo = respuesta.json()

    assert [r["identificador_externo"] for r in cuerpo["resultados"]] == ["cp-1"]
    assert all(r["identificador_externo"] != "no-1" for r in cuerpo["resultados"])


def test_filtro_no_declarado_devuelve_422(client: TestClient) -> None:
    respuesta = client.get(
        "/v1/search", params={"q": "texto de prueba", "filtro.clave_inventada": "x"}
    )
    assert respuesta.status_code == 422
