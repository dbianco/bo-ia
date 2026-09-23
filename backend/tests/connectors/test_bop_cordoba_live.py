"""T025: chequeo manual ocasional contra el sitio real del BOP. Marcado
`live` — excluido por defecto y de CI (SC-006); correr a mano con
`pytest -m live`."""
import pytest

from src.connectors.bop_cordoba.connector import ConectorBopCordoba
from src.connectors.protocol import ErrorDescubrimiento
from src.ingestor.contract import DocumentoNormalizado


@pytest.mark.live
def test_conector_bop_contra_el_sitio_real() -> None:
    """Usa la misma fecha que el PoC (docs/superpowers/reports/2026-09-23-scraping-poc.md),
    donde ya se confirmó que hay 30 anuncios publicados."""
    conector = ConectorBopCordoba()
    config = {
        "url_template": "https://bop.dipucordoba.es/dia/{fecha}",
        "fecha": "2026-06-05",
        "proceso_timeout_segundos": 120,
    }

    items = list(conector.descubrir(fuente_clave="cordoba-provincial", config=config))
    documentos = [i for i in items if isinstance(i, DocumentoNormalizado)]
    errores = [i for i in items if isinstance(i, ErrorDescubrimiento)]

    assert len(documentos) + len(errores) > 0
    if documentos:
        assert documentos[0].texto.strip() != ""
