"""T015: chequeo manual ocasional contra el dataset real de datos.gob.ar.
Marcado `live` — excluido por defecto y de CI (SC-007); correr a mano con
`pytest -m live`."""
import pytest

from src.connectors.comprar_gob_ar.connector import ConectorComprarGobAr
from src.ingestor.contract import DocumentoNormalizado


@pytest.mark.live
def test_conector_comprar_gob_ar_contra_el_dataset_real() -> None:
    conector = ConectorComprarGobAr()
    config = {
        "csv_url": "https://infra.datos.gob.ar/catalog/jgm/dataset/4/distribution/4.21/download/Convocatorias.csv",
        "anio_desde": 2026,
        "timeout_segundos": 120,
    }

    items = list(conector.descubrir(fuente_clave="comprar-ar-nacional", config=config))
    documentos = [i for i in items if isinstance(i, DocumentoNormalizado)]

    assert len(documentos) >= 1
    assert documentos[0].metadata["organismo"]
    assert documentos[0].metadata["jurisdiccion"] == "nacional"
