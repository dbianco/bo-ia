"""Plan 7: declared filters are filled from the source configuration."""
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.installation import (
    FiltroSeleccion,
    FuenteConfig,
    InstallationConfig,
    cargar_installation_config,
    unfillable_filters,
    upsert_fuentes,
)
from src.connectors.registry import CONECTORES, METADATA_KEYS
from src.db.models import Fuente

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _installation(**source) -> InstallationConfig:
    return InstallationConfig(
        nombre="x",
        fuentes=[FuenteConfig(clave="f", nombre="f", **source)],
        filtros=[
            FiltroSeleccion(clave="provincia", etiqueta="Provincia"),
            FiltroSeleccion(clave="municipio", etiqueta="Municipio"),
        ],
    )


def test_fixed_metadata_is_saved_with_the_source(db_session: Session) -> None:
    upsert_fuentes(db_session, _installation(metadata={"provincia": "Córdoba"}))
    assert db_session.scalar(select(Fuente)).config == {"metadata": {"provincia": "Córdoba"}}


def test_changing_or_removing_it_updates_the_source_and_keeps_other_settings(db_session: Session) -> None:
    db_session.add(Fuente(clave="f", nombre="f", config={"other": 1, "metadata": {"provincia": "Old"}}))
    db_session.commit()
    upsert_fuentes(db_session, _installation(metadata={"provincia": "Córdoba"}))
    assert db_session.scalar(select(Fuente)).config == {"other": 1, "metadata": {"provincia": "Córdoba"}}
    upsert_fuentes(db_session, _installation())
    assert db_session.scalar(select(Fuente)).config == {"other": 1}


def test_a_filter_that_no_source_can_fill_is_reported() -> None:
    connector = {"tipo": "t", "frecuencia_minutos": 1}
    assert unfillable_filters(_installation(), {}) == ["provincia", "municipio"]
    assert unfillable_filters(_installation(metadata={"provincia": "Córdoba"}), {}) == ["municipio"]
    keys = {"t": frozenset({"municipio"})}
    assert unfillable_filters(_installation(metadata={"provincia": "C"}, conector=connector), keys) == []
    assert unfillable_filters(_installation(conector=connector), keys) == ["provincia"]
    assert unfillable_filters(_installation(conector={**connector, "tipo": "unknown"}), keys) == ["provincia", "municipio"]


def test_every_registered_connector_declares_its_metadata() -> None:
    assert set(METADATA_KEYS) == set(CONECTORES)


@pytest.mark.parametrize("name", ["installation.yaml", "installation-licitaciones.yaml"])
def test_every_filter_of_the_shipped_installations_can_be_filled(name: str) -> None:
    assert unfillable_filters(cargar_installation_config(CONFIG_DIR / name), METADATA_KEYS) == []


def test_startup_warns_about_filters_that_cannot_be_filled(db_session: Session, monkeypatch, caplog) -> None:
    from fastapi.testclient import TestClient

    from src.api import main

    installation = _installation(metadata={"provincia": "Córdoba"})
    installation.seed = False
    monkeypatch.setattr(main.logger, "disabled", False)  # the migrations of the fixture disable it
    monkeypatch.setattr(main, "get_installation_config", lambda: installation)
    monkeypatch.setattr(main.deps, "_engine", lambda: db_session.get_bind())
    monkeypatch.setattr(main, "get_embedder", lambda: None)
    with caplog.at_level("WARNING", logger="contextcrawl"), TestClient(main.app):
        pass
    messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING" and r.name == "contextcrawl"]
    assert len(messages) == 1 and "municipio" in messages[0]
