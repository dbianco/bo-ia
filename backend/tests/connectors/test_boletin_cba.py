"""Conector `boletin-cba-pdf-diario`: construcción de URL por sección/
fecha y extracción de texto (T008-T009), Etapa 5, FR-005 a FR-009."""
from datetime import date
from pathlib import Path

from src.connectors.boletin_cba.connector import ConectorBoletinCba, construir_url
from src.connectors.protocol import ErrorDescubrimiento
from src.ingestor.contract import DocumentoNormalizado

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "boletin_cba"

PLANTILLA_REAL = "https://boletinoficial.cba.gov.ar/wp-content/4p96humuzp/{anio}/{mes}/{seccion}_Secc_{ddmmyy}.pdf"


def test_construir_url_arma_la_url_predecible_del_sitio_real() -> None:
    url = construir_url(PLANTILLA_REAL, seccion=4, fecha=date(2026, 9, 24))

    assert url == "https://boletinoficial.cba.gov.ar/wp-content/4p96humuzp/2026/09/4_Secc_240926.pdf"


def _config(**overrides) -> dict:
    plantilla_fixture = (FIXTURES / "4_Secc_sample.pdf").resolve().as_uri()
    base = {
        "url_template": plantilla_fixture,
        "secciones": [4],
        "fecha": "2026-09-24",
    }
    base.update(overrides)
    return base


def test_conector_produce_un_documento_por_seccion_con_texto_extraido() -> None:
    conector = ConectorBoletinCba()

    items = list(conector.descubrir(fuente_clave="cba-provincial-licitaciones", config=_config()))

    assert len(items) == 1
    documento = items[0]
    assert isinstance(documento, DocumentoNormalizado)
    assert documento.identificador_externo == "4_Secc_240926"
    assert documento.fecha == date(2026, 9, 24)
    assert "LICITACIONES" in documento.texto
    assert documento.metadata["jurisdiccion"] == "provincial"
    assert documento.metadata["seccion"] == 4


def test_seccion_no_publicada_produce_un_error_sin_abortar_el_resto() -> None:
    # Plantilla que solo resuelve a un archivo real para la sección 4; la
    # sección 9 cae a una ruta inexistente y debe registrarse como error
    # puntual sin perder el documento de la sección 4.
    plantilla = str(FIXTURES.resolve()) + "/{seccion}_Secc_sample.pdf"
    plantilla_uri = "file://" + plantilla

    conector = ConectorBoletinCba()

    items = list(
        conector.descubrir(
            fuente_clave="cba-provincial-licitaciones",
            config=_config(url_template=plantilla_uri, secciones=[4, 9]),
        )
    )

    documentos = [i for i in items if isinstance(i, DocumentoNormalizado)]
    errores = [i for i in items if isinstance(i, ErrorDescubrimiento)]
    assert len(documentos) == 1
    assert len(errores) == 1
    assert errores[0].identificador_externo == "9_Secc_240926"
