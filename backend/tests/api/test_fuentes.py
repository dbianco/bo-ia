"""T021: POST /v1/fuentes/{clave}/ejecutar — dispara una ejecución manual
(FR-011)."""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_installation_config, get_session
from src.api.main import app
from src.config.installation import ConectorConfig, FuenteConfig, InstallationConfig
from src.db.models import Fuente
from src.ingestor.contract import DocumentoNormalizado
from src.processor.embeddings import FakeEmbeddingProvider


class _ConectorFake:
    def descubrir(self, *, fuente_clave: str, config: dict):
        yield DocumentoNormalizado(
            fuente_clave=fuente_clave,
            identificador_externo="manual-1",
            fecha=datetime.date(2026, 1, 1),
            texto="texto de prueba",
            url_fuente="https://example.org/manual-1",
        )


@pytest.fixture()
def installation() -> InstallationConfig:
    return InstallationConfig(
        nombre="test",
        fuentes=[
            FuenteConfig(
                clave="fuente-manual", nombre="Fuente manual", conector=ConectorConfig(tipo="fake", frecuencia_minutos=1440)
            ),
            FuenteConfig(clave="fuente-sin-conector", nombre="Sin conector", conector=None),
        ],
    )


@pytest.fixture()
def client(db_session: Session, installation: InstallationConfig, monkeypatch):
    from src.api import fuentes as fuentes_module

    monkeypatch.setitem(fuentes_module.CONECTORES, "fake", _ConectorFake)
    monkeypatch.setitem(fuentes_module.VERSIONES, "fake", "fake-v1")

    def _get_session_override():
        yield db_session

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[get_embedder] = lambda: FakeEmbeddingProvider()
    app.dependency_overrides[get_installation_config] = lambda: installation
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_ejecutar_fuente_dispara_una_ejecucion_y_devuelve_su_resultado(
    client: TestClient, db_session: Session
) -> None:
    db_session.add(Fuente(clave="fuente-manual", nombre="Fuente manual", config={}))
    db_session.commit()

    respuesta = client.post("/v1/fuentes/fuente-manual/ejecutar")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "completada"
    assert cuerpo["descubiertos"] == 1
    assert cuerpo["nuevos"] == 1


def test_ejecutar_fuente_inexistente_devuelve_404(client: TestClient) -> None:
    respuesta = client.post("/v1/fuentes/no-existe/ejecutar")
    assert respuesta.status_code == 404


def test_ejecutar_fuente_sin_conector_configurado_devuelve_404(client: TestClient, db_session: Session) -> None:
    db_session.add(Fuente(clave="fuente-sin-conector", nombre="Sin conector", config={}))
    db_session.commit()

    respuesta = client.post("/v1/fuentes/fuente-sin-conector/ejecutar")
    assert respuesta.status_code == 404
