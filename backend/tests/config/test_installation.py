"""T011: carga y validación de `installation.yaml` (FR-007, FR-008)."""
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.installation import (
    FiltroRangoNumerico,
    FiltroSeleccion,
    InstallationConfig,
    InstallationConfigInvalida,
    cargar_installation_config,
    upsert_fuentes,
)
from src.db.models import Fuente

YAML_VALIDO = """
nombre: Boletines Córdoba
fuentes:
  - clave: cordoba-provincial
    nombre: Boletín Oficial de Córdoba
  - clave: carlos-paz-municipal
    nombre: Boletín Municipal de Carlos Paz
filtros:
  - clave: provincia
    etiqueta: Provincia
    tipo: seleccion
  - clave: municipio
    etiqueta: Municipio
    tipo: seleccion
  - clave: presupuesto_estimado
    etiqueta: Presupuesto estimado
    tipo: rango_numerico
"""


def test_cargar_installation_config_valido(tmp_path: Path) -> None:
    ruta = tmp_path / "installation.yaml"
    ruta.write_text(YAML_VALIDO, encoding="utf-8")

    config = cargar_installation_config(ruta)

    assert isinstance(config, InstallationConfig)
    assert config.nombre == "Boletines Córdoba"
    assert [f.clave for f in config.fuentes] == ["cordoba-provincial", "carlos-paz-municipal"]
    assert isinstance(config.filtros[0], FiltroSeleccion)
    assert isinstance(config.filtros[2], FiltroRangoNumerico)
    assert config.seed is True  # default: no cambia el comportamiento existente


def test_cargar_installation_config_con_seed_false(tmp_path: Path) -> None:
    ruta = tmp_path / "installation.yaml"
    ruta.write_text(YAML_VALIDO.replace("nombre: Boletines Córdoba", "nombre: Licitaciones\nseed: false"), encoding="utf-8")

    config = cargar_installation_config(ruta)

    assert config.seed is False


def test_cargar_installation_config_archivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(InstallationConfigInvalida):
        cargar_installation_config(tmp_path / "no-existe.yaml")


def test_cargar_installation_config_yaml_invalido(tmp_path: Path) -> None:
    ruta = tmp_path / "installation.yaml"
    ruta.write_text("esto: [no es yaml valido", encoding="utf-8")

    with pytest.raises(InstallationConfigInvalida):
        cargar_installation_config(ruta)


def test_cargar_installation_config_sin_campos_obligatorios(tmp_path: Path) -> None:
    ruta = tmp_path / "installation.yaml"
    ruta.write_text("fuentes: []\n", encoding="utf-8")  # falta 'nombre'

    with pytest.raises(InstallationConfigInvalida):
        cargar_installation_config(ruta)


def test_upsert_fuentes_crea_y_es_idempotente(tmp_path: Path, db_session: Session) -> None:
    ruta = tmp_path / "installation.yaml"
    ruta.write_text(YAML_VALIDO, encoding="utf-8")
    config = cargar_installation_config(ruta)

    creadas_primero = upsert_fuentes(db_session, config)
    creadas_segundo = upsert_fuentes(db_session, config)

    assert creadas_primero == 2
    assert creadas_segundo == 0
    claves = db_session.scalars(select(Fuente.clave)).all()
    assert sorted(claves) == ["carlos-paz-municipal", "cordoba-provincial"]
