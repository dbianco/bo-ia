"""T012: GET /v1/config expone los filtros declarados (FR-010)."""
from fastapi.testclient import TestClient

from src.api.deps import get_installation_config
from src.api.main import app
from src.config.installation import FiltroSeleccion, InstallationConfig


def test_config_expone_filtros_declarados() -> None:
    config = InstallationConfig(
        nombre="Boletines Córdoba",
        filtros=[
            FiltroSeleccion(clave="provincia", etiqueta="Provincia"),
            FiltroSeleccion(clave="municipio", etiqueta="Municipio"),
        ],
    )
    app.dependency_overrides[get_installation_config] = lambda: config
    try:
        respuesta = TestClient(app).get("/v1/config")
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["nombre"] == "Boletines Córdoba"
    assert cuerpo["filtros"] == [
        {"clave": "provincia", "etiqueta": "Provincia", "tipo": "seleccion"},
        {"clave": "municipio", "etiqueta": "Municipio", "tipo": "seleccion"},
    ]
