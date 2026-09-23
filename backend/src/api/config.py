"""Endpoint de configuración de instalación: GET /v1/config (FR-010).

Expone los filtros declarados en `installation.yaml`, para que la interfaz
web (y cualquier otro cliente) genere sus controles sin código propio por
instalación.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_installation_config
from src.config.installation import InstallationConfig

router = APIRouter()


@router.get("/v1/config")
def obtener_config(installation: InstallationConfig = Depends(get_installation_config)) -> dict:
    return {
        "nombre": installation.nombre,
        "filtros": [
            {"clave": f.clave, "etiqueta": f.etiqueta, "tipo": f.tipo} for f in installation.filtros
        ],
    }
