"""Configuración de instalación (`installation.yaml`, sección 8 del design
spec): nombre, fuentes iniciales y filtros declarados por esta
instalación. "Configuración antes que código" (sección 3.4): agregar o
renombrar un filtro no debe requerir tocar el motor.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import literal, not_, select, update
from sqlalchemy.dialects.postgresql import JSONB, array
from sqlalchemy.orm import Session

from src.db.models import Documento, Fuente


class InstallationConfigInvalida(ValueError):
    """El archivo de configuración de instalación no existe o no es
    válido (FR-007): el servicio no debe arrancar con configuración
    parcial."""


class FiltroSeleccion(BaseModel):
    clave: str
    etiqueta: str
    tipo: Literal["seleccion"] = "seleccion"


class FiltroRangoNumerico(BaseModel):
    clave: str
    etiqueta: str
    tipo: Literal["rango_numerico"] = "rango_numerico"


Filtro = Annotated[FiltroSeleccion | FiltroRangoNumerico, Field(discriminator="tipo")]


class ConectorConfig(BaseModel):
    """Bloque opcional de conector de una fuente (Etapa 2, FR-013): `tipo`
    referencia una clave de `src/connectors/registry.py`, no un import
    directo, para que declarar una fuente nueva no requiera tocar código."""

    tipo: str
    frecuencia_minutos: float
    config: dict = Field(default_factory=dict)


class FuenteConfig(BaseModel):
    clave: str
    nombre: str
    # Values that are the same for every document of the source, such as the
    # province. They are added to each document, so its filters find it.
    metadata: dict[str, str | int | float] = Field(default_factory=dict)
    conector: ConectorConfig | None = None


class InstallationConfig(BaseModel):
    nombre: str
    fuentes: list[FuenteConfig] = Field(default_factory=list)
    filtros: list[Filtro] = Field(default_factory=list)
    # Etapa 5: `sembrar_si_vacio` carga datos de ejemplo específicos del
    # Boletín (sección 8 del design spec); una instalación de otro
    # vertical no debe recibirlos. Default `True` para no cambiar el
    # comportamiento de la instalación de boletines ya existente.
    seed: bool = True


def cargar_installation_config(ruta: str | Path) -> InstallationConfig:
    path = Path(ruta)
    if not path.exists():
        raise InstallationConfigInvalida(f"No existe el archivo de configuración de instalación: {path}")
    try:
        datos = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise InstallationConfigInvalida(f"YAML inválido en {path}: {exc}") from exc
    try:
        return InstallationConfig.model_validate(datos)
    except ValidationError as exc:
        raise InstallationConfigInvalida(f"Configuración de instalación inválida ({path}): {exc}") from exc


def fill_fixed_metadata(session: Session, fuente: Fuente) -> int:
    """Adds the fixed metadata of a source to its documents that do not have it.
    A value that a document has is kept. Returns how many documents changed."""
    fixed = (fuente.config or {}).get("metadata", {})
    if not fixed:
        return 0
    result = session.execute(
        update(Documento)
        .where(Documento.fuente_id == fuente.id, not_(Documento.metadata_.has_all(array(list(fixed)))))
        .values(metadata_=literal(fixed, type_=JSONB).op("||")(Documento.metadata_))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


def upsert_fuentes(session: Session, config: InstallationConfig) -> int:
    """Crea o actualiza las fuentes declaradas por la instalación,
    idempotente por `clave` (FR-008). Devuelve la cantidad de fuentes
    nuevas creadas.

    The fixed metadata of a source is also added to the documents it already
    has, so that the filters find them."""
    creadas = 0
    for declarada in config.fuentes:
        existente = session.scalar(select(Fuente).where(Fuente.clave == declarada.clave))
        fijos = {"metadata": declarada.metadata} if declarada.metadata else {}
        if existente is None:
            session.add(Fuente(clave=declarada.clave, nombre=declarada.nombre, config=fijos))
            creadas += 1
            continue
        if existente.nombre != declarada.nombre:
            existente.nombre = declarada.nombre
        existente.config = {k: v for k, v in (existente.config or {}).items() if k != "metadata"} | fijos
        fill_fixed_metadata(session, existente)
    session.commit()
    return creadas


def unfillable_filters(config: InstallationConfig, connector_keys: Mapping[str, frozenset[str]]) -> list[str]:
    """Declared filters that no configured source can fill: searching by one of
    them excludes every document that is collected. `connector_keys` are the
    metadata keys each type of connector may write."""
    fillable: set[str] = set()
    for fuente in config.fuentes:
        fillable.update(fuente.metadata)
        if fuente.conector is not None:
            fillable.update(connector_keys.get(fuente.conector.tipo, frozenset()))
    return [f.clave for f in config.filtros if f.clave not in fillable]
