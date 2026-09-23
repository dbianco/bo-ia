"""Registro de tipos de conector: `installation.yaml` los referencia por
`tipo` (FR-013), no por importar código directamente."""
from __future__ import annotations

from src.connectors.bop_cordoba.connector import VERSION as BOP_CORDOBA_VERSION
from src.connectors.bop_cordoba.connector import ConectorBopCordoba
from src.connectors.protocol import Conector

CONECTORES: dict[str, type[Conector]] = {
    "bop-cordoba-scrapy": ConectorBopCordoba,
}

VERSIONES: dict[str, str] = {
    "bop-cordoba-scrapy": BOP_CORDOBA_VERSION,
}
