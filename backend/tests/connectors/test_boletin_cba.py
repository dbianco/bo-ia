"""Conector `boletin-cba-pdf-diario`: construcción de URL por sección/
fecha y extracción de texto (T008-T009), Etapa 5, FR-005 a FR-009."""
from datetime import date
from pathlib import Path

from src.connectors.boletin_cba.connector import ConectorBoletinCba, construir_url
from src.connectors.pdf_pages import extract_pages, remove_running_lines
from src.connectors.protocol import ErrorDescubrimiento
from src.ingestor.contract import DocumentoNormalizado
from src.synthetic.issues import generate_issue
from src.synthetic.pdf import write_pdf

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


def _descubrir(config: dict) -> list:
    return list(ConectorBoletinCba().descubrir(fuente_clave="cba-provincial-licitaciones", config=config))


def test_connector_produces_one_document_per_notice_of_the_real_pdf() -> None:
    """Plan 7. Before it, the whole section was one document."""
    items = _descubrir(_config())
    assert all(isinstance(i, DocumentoNormalizado) for i in items)
    notices = [i for i in items if i.notice_number]
    assert len(notices) == 35  # counted on the rendered PDF, see test_boletin_cba_segmenter.py
    assert len({i.identificador_externo for i in items}) == len(items)

    notice = next(i for i in notices if i.notice_number == "688769")
    assert notice.identificador_externo == "4_Secc_240926_N688769"
    assert notice.fecha == date(2026, 9, 24)
    assert notice.issue == "4_Secc_240926"
    assert notice.url_fuente.endswith("4_Secc_sample.pdf#page=4")
    assert [page for _, page in notice.page_starts] == [4, 5]
    assert notice.titulo.startswith("Aviso Nº 688769 — COOPERATIVA DE SERVICIOS PÚBLICOS")
    assert "PARQUE SOLAR FOTOVOLTAICO" in notice.texto
    assert notice.metadata == {
        "jurisdiccion": "provincial",
        "seccion": 4,
        "publication_days": 3,
        "last_publication_date": "2026-09-28",
    }
    assert notice.searchable


def test_the_cover_is_kept_but_not_searchable() -> None:
    cover = [i for i in _descubrir(_config()) if not i.notice_number]
    assert [c.identificador_externo for c in cover] == ["4_Secc_240926_cover"]
    assert "SUMARIO" in cover[0].texto
    assert not cover[0].searchable
    assert cover[0].issue == "4_Secc_240926"


def test_no_text_of_the_issue_is_lost_between_extraction_and_documents() -> None:
    cleaned = "\n".join(remove_running_lines(extract_pages((FIXTURES / "4_Secc_sample.pdf").read_bytes())))
    documents = "".join(i.texto for i in _descubrir(_config()))
    assert sorted(documents) == sorted(cleaned)


def _pdf(tmp_path: Path, pages: list[str]) -> str:
    path = tmp_path / "issue.pdf"
    path.write_bytes(write_pdf(pages))
    return path.resolve().as_uri()


def test_a_section_with_another_layout_is_one_searchable_unsegmented_document(tmp_path: Path) -> None:
    url = _pdf(tmp_path, ["LEGISLACION\nDecreto 1. Visto y considerando.", "Artículo 1. Publíquese."])
    (document,) = _descubrir(_config(url_template=url, secciones=[1]))
    assert document.identificador_externo == "1_Secc_240926_unsegmented"
    assert document.notice_number is None and document.searchable
    assert [page for _, page in document.page_starts] == [1, 2]
    assert document.url_fuente == url + "#page=1"
    assert document.titulo.startswith("1° Sección")


def test_text_without_closing_line_becomes_an_unsegmented_document(tmp_path: Path) -> None:
    url = _pdf(tmp_path, ["A\nuno.\n1 día - Nº 5 - s/c - 24/9/2026 - BOE\nAviso sin cierre."])
    items = _descubrir(_config(url_template=url))
    assert [i.identificador_externo for i in items] == ["4_Secc_240926_N5", "4_Secc_240926_unsegmented"]
    assert items[1].texto == "Aviso sin cierre." and items[1].searchable


def test_a_number_printed_twice_in_an_issue_keeps_both_notices(tmp_path: Path) -> None:
    closing = "1 día - Nº 5 - s/c - 24/9/2026 - BOE"
    url = _pdf(tmp_path, [f"A\nuno.\n{closing}\nB\ndos.\n{closing}"])
    ids = [i.identificador_externo for i in _descubrir(_config(url_template=url))]
    assert ids == ["4_Secc_240926_N5", "4_Secc_240926_N5-2"]


def test_the_town_of_a_municipal_notice_is_metadata(tmp_path: Path) -> None:
    url = _pdf(tmp_path, ["MUNICIPALIDAD DE CARLOS PAZ\nOrdenanza.\n1 día - Nº 5 - s/c - 24/9/2026 - BOE"])
    (document,) = _descubrir(_config(url_template=url, secciones=[5]))
    assert document.metadata["municipio"] == "Carlos Paz"


def test_generated_issue_end_to_end_through_a_pdf_file(tmp_path: Path) -> None:
    issue = generate_issue(77, notices=40, quotes=0.3)
    assert len(issue.pages) > 4
    url = _pdf(tmp_path, issue.pages)
    items = _descubrir(_config(url_template=url, fecha=issue.date.isoformat()))
    notices = [i for i in items if i.notice_number]
    assert [i.notice_number for i in notices] == [n.number for n in issue.notices]
    assert [[p for _, p in (i.page_starts[0], i.page_starts[-1])] for i in notices] == [
        [n.pages[0], n.pages[-1]] for n in issue.notices
    ]


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
    assert len(documentos) == 36  # 35 notices and the cover
    assert len(errores) == 1
    assert errores[0].identificador_externo == "9_Secc_240926"
