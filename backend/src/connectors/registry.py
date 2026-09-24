"""Registro de tipos de conector: `installation.yaml` los referencia por
`tipo` (FR-013), no por importar código directamente."""
from __future__ import annotations

from src.connectors.boletin_cba.connector import VERSION as BOLETIN_CBA_VERSION
from src.connectors.boletin_cba.connector import ConectorBoletinCba
from src.connectors.bop_cordoba.connector import VERSION as BOP_CORDOBA_VERSION
from src.connectors.bop_cordoba.connector import ConectorBopCordoba
from src.connectors.comprar_gob_ar.connector import VERSION as COMPRAR_GOB_AR_VERSION
from src.connectors.comprar_gob_ar.connector import ConectorComprarGobAr
from src.connectors.protocol import Conector

CONECTORES: dict[str, type[Conector]] = {
    "bop-cordoba-scrapy": ConectorBopCordoba,
    "comprar-gob-ar-csv": ConectorComprarGobAr,
    "boletin-cba-pdf-diario": ConectorBoletinCba,
}

VERSIONES: dict[str, str] = {
    "bop-cordoba-scrapy": BOP_CORDOBA_VERSION,
    "comprar-gob-ar-csv": COMPRAR_GOB_AR_VERSION,
    "boletin-cba-pdf-diario": BOLETIN_CBA_VERSION,
}
