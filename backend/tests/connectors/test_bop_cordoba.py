"""Conector del Boletín Oficial de la Provincia de Córdoba (BOP): extracción
de texto de PDF (T010), conector completo con fixtures (T012-T013, T017)."""
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.connectors.bop_cordoba.connector import ConectorBopCordoba
from src.connectors.bop_cordoba.pdf import ErrorExtraccionPDF, extraer_texto_pdf
from src.connectors.protocol import ErrorDescubrimiento
from src.connectors.runner import ejecutar_conector
from src.db.models import Fuente
from src.ingestor.contract import DocumentoNormalizado
from src.processor.embeddings import FakeEmbeddingProvider

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bop_cordoba"


def test_extraer_texto_pdf_devuelve_el_texto_real() -> None:
    contenido = (FIXTURES / "pdfs" / "BOP-C-2026-0001.pdf").read_bytes()

    texto = extraer_texto_pdf(contenido)

    assert "Decreto 12/2026" in texto
    assert "presupuesto provincial" in texto


def test_extraer_texto_pdf_con_pdf_corrupto_levanta_error_claro() -> None:
    contenido = (FIXTURES / "pdfs" / "BOP-C-2026-0004.pdf").read_bytes()

    with pytest.raises(ErrorExtraccionPDF):
        extraer_texto_pdf(contenido)


def _config_fixture() -> dict:
    index_url = (FIXTURES / "index.html").resolve().as_uri()
    return {"url_template": index_url, "fecha": "2026-06-05", "proceso_timeout_segundos": 60}


def test_conector_bop_produce_documentos_normalizados_desde_el_fixture() -> None:
    """SC-001: el conector, corriendo contra el fixture del índice, produce
    un `DocumentoNormalizado` por anuncio con PDF legible, con el texto
    real extraído del PDF."""
    conector = ConectorBopCordoba()

    items = list(conector.descubrir(fuente_clave="cordoba-provincial", config=_config_fixture()))

    documentos = [i for i in items if isinstance(i, DocumentoNormalizado)]
    errores = [i for i in items if isinstance(i, ErrorDescubrimiento)]

    assert len(documentos) == 3, [d.identificador_externo for d in documentos]
    assert len(errores) == 1
    ids = {d.identificador_externo for d in documentos}
    assert ids == {"BOP-C-2026-0001", "BOP-C-2026-0002", "BOP-C-2026-0003"}

    uno = next(d for d in documentos if d.identificador_externo == "BOP-C-2026-0001")
    assert "Decreto 12/2026" in uno.texto
    assert uno.fecha.isoformat() == "2026-06-05"
    assert uno.metadata.get("organismo") == "Ministerio de Hacienda"


def test_conector_bop_reporta_el_pdf_ilegible_como_error() -> None:  # SC-004
    conector = ConectorBopCordoba()

    items = list(conector.descubrir(fuente_clave="cordoba-provincial", config=_config_fixture()))
    errores = [i for i in items if isinstance(i, ErrorDescubrimiento)]

    assert len(errores) == 1
    assert errores[0].identificador_externo == "BOP-C-2026-0004"


def test_reejecutar_el_conector_bop_es_idempotente(db_session: Session) -> None:  # SC-002
    fuente = Fuente(clave="cordoba-provincial", nombre="BOP Córdoba", config={})
    db_session.add(fuente)
    db_session.flush()
    conector = ConectorBopCordoba()
    embedder = FakeEmbeddingProvider()

    primera = ejecutar_conector(
        db_session, embedder, fuente, conector, _config_fixture(), version_conector="test"
    )
    segunda = ejecutar_conector(
        db_session, embedder, fuente, conector, _config_fixture(), version_conector="test"
    )

    assert primera.nuevos == 3
    assert segunda.nuevos == 0
    assert segunda.existentes == 3
    assert segunda.descubiertos == segunda.nuevos + segunda.existentes + segunda.errores
