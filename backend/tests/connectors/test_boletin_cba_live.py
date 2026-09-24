"""T015: chequeo manual ocasional contra el sitio real de
boletinoficial.cba.gov.ar. Marcado `live` — excluido por defecto y de CI
(SC-007); correr a mano con `pytest -m live`."""
import datetime

import pytest

from src.connectors.boletin_cba.connector import ConectorBoletinCba
from src.ingestor.contract import DocumentoNormalizado


@pytest.mark.live
def test_conector_boletin_cba_contra_el_sitio_real() -> None:
    conector = ConectorBoletinCba()
    config = {
        "url_template": (
            "https://boletinoficial.cba.gov.ar/wp-content/4p96humuzp/"
            "{anio}/{mes}/{seccion}_Secc_{ddmmyy}.pdf"
        ),
        "secciones": [4],
        "fecha": datetime.date.today().isoformat(),
        "timeout_segundos": 60,
    }

    items = list(conector.descubrir(fuente_clave="cba-provincial-licitaciones", config=config))

    assert len(items) == 1
    documento = items[0]
    assert isinstance(documento, DocumentoNormalizado)
    assert documento.texto.strip() != ""
