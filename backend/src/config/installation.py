"""Configuración de instalación (`installation.yaml`, sección 8 del design
spec): nombre, fuentes iniciales y filtros declarados por esta
instalación. "Configuración antes que código" (sección 3.4): agregar o
renombrar un filtro no debe requerir tocar el motor.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Fuente


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


class FuenteConfig(BaseModel):
    clave: str
    nombre: str


class InstallationConfig(BaseModel):
    nombre: str
    fuentes: list[FuenteConfig] = Field(default_factory=list)
    filtros: list[Filtro] = Field(default_factory=list)


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


def upsert_fuentes(session: Session, config: InstallationConfig) -> int:
    """Crea o actualiza las fuentes declaradas por la instalación,
    idempotente por `clave` (FR-008). Devuelve la cantidad de fuentes
    nuevas creadas."""
    creadas = 0
    for declarada in config.fuentes:
        existente = session.scalar(select(Fuente).where(Fuente.clave == declarada.clave))
        if existente is None:
            session.add(Fuente(clave=declarada.clave, nombre=declarada.nombre, config={}))
            creadas += 1
        elif existente.nombre != declarada.nombre:
            existente.nombre = declarada.nombre
    session.commit()
    return creadas
