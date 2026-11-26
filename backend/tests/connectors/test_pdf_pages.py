"""Plan 7: page-by-page extraction and removal of running headers."""
import random
from pathlib import Path

import pytest

from src.connectors.bop_cordoba.pdf import ErrorExtraccionPDF, extraer_texto_pdf
from src.connectors.pdf_pages import extract_pages, remove_running_lines
from src.synthetic.issues import generate_issue
from src.synthetic.pdf import write_pdf

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "boletin_cba" / "4_Secc_sample.pdf"
HEADER = ["BOLETIN OFICIAL", "AÑO CXIII - Nº 186", "JUEVES 24"]


def _with_header(bodies: list[list[str]], numbered=True) -> list[str]:
    """The first page is a cover without header, like the real issues."""
    pages = ["\n".join(["PORTADA", *bodies[0]])]
    for number, body in enumerate(bodies[1:], start=2):
        pages.append("\n".join([*([str(number)] if numbered else []), *HEADER, *body]))
    return pages


def _lines(pages: list[str]) -> list[str]:
    return [line for page in pages for line in page.split("\n") if line]


def test_extracts_one_text_per_page_of_the_real_pdf() -> None:
    pages = extract_pages(FIXTURE.read_bytes())
    assert len(pages) == 8
    assert "3 días - Nº 688404 - s/c - 24/9/2026 - BOE" in pages[0]
    assert "5 días - Nº 687583 - s/c - 28/9/2026 - BOE" in pages[7]


def test_the_existing_extraction_is_unchanged() -> None:
    content = FIXTURE.read_bytes()
    assert extraer_texto_pdf(content) == "\n".join(extract_pages(content))


@pytest.mark.parametrize("content", [b"", b"not a pdf", b"%PDF-1.4\n%%EOF"])
def test_an_unreadable_pdf_is_an_extraction_error(content: bytes) -> None:
    with pytest.raises(ErrorExtraccionPDF):
        extract_pages(content)


def test_a_pdf_without_text_is_an_extraction_error() -> None:
    with pytest.raises(ErrorExtraccionPDF):
        extract_pages(write_pdf(["", ""]))


def test_two_columns_are_read_in_content_order() -> None:
    issue = generate_issue(2, notices=25)
    assert _lines(extract_pages(write_pdf(issue.pages))) == _lines(issue.pages)


def test_removes_the_header_of_the_real_pdf_and_nothing_else() -> None:
    pages = extract_pages(FIXTURE.read_bytes())
    cleaned = remove_running_lines(pages)
    assert cleaned[0] == pages[0]
    for number, (before, after) in enumerate(zip(pages[1:], cleaned[1:], strict=True), start=2):
        removed = before.split("\n")[:9]
        assert removed[0] == str(number)
        assert removed[8].startswith("2026 - Año de los Derechos Humanos")
        assert after == "\n".join(before.split("\n")[9:])


def test_removes_header_and_footer_by_repetition() -> None:
    bodies = [[f"texto {i} {j}" for j in range(4)] for i in range(5)]
    pages = _with_header(bodies)
    pages = [pages[0], *(p + "\nPie de página" for p in pages[1:])]
    assert remove_running_lines(pages) == ["\n".join(["PORTADA", *bodies[0]]), *("\n".join(b) for b in bodies[1:])]


@pytest.mark.parametrize("template", ["BOLETIN OFICIAL DE LA PROVINCIA {}", "Página {} de 6", "- {} -"])
def test_a_page_number_attached_to_the_header_is_recognized(template: str) -> None:
    bodies = [[f"cuerpo {i} {j}" for j in range(3)] for i in range(6)]
    pages = ["\n".join([template.format(i), "ENCABEZADO FIJO", *body]) for i, body in enumerate(bodies, start=1)]
    assert remove_running_lines(pages) == ["\n".join(body) for body in bodies]


def test_numbers_that_are_not_the_page_number_do_not_make_a_header() -> None:
    """Closing lines end many pages and differ only in their digits."""
    pages = _with_header([[f"texto {i}", f"3 días - Nº 68{i}2{i}9 - s/c - 24/9/2026 - BOE"] for i in range(6)])
    assert [p.split("\n")[-1] for p in remove_running_lines(pages)] == [p.split("\n")[-1] for p in pages]


def test_consecutive_notice_numbers_are_not_a_page_number() -> None:
    """One notice per page, numbered in sequence, moves in step with the page number."""
    pages = _with_header([[f"texto {i}", f"1 día - Nº {688200 + i} - s/c - 24/9/2026 - BOE"] for i in range(6)])
    cleaned = remove_running_lines(pages)
    assert [p.split("\n")[-1] for p in cleaned] == [p.split("\n")[-1] for p in pages]


def test_body_text_that_counts_along_with_the_pages_is_kept() -> None:
    """One article per page: "Artículo 2" on page 2 looks like a numbered header."""
    bodies = [[f"Artículo {page}", f"texto {'abcdef'[page - 1]}", f"Anexo {page}"] for page in range(1, 7)]
    cleaned = remove_running_lines(_with_header(bodies))
    assert [page.split("\n") for page in cleaned[1:]] == bodies[1:]


def test_a_notice_title_that_opens_several_pages_is_kept() -> None:
    title = ["AGENCIA CÓRDOBA", "MINISTERIO DE EDUCACION."]
    bodies = [[f"inicio {i}", *title, f"aviso {i}"] if i < 2 else [*title, f"aviso {i}", "abcdef"[i]] for i in range(6)]
    cleaned = remove_running_lines(_with_header(bodies))
    assert [page.split("\n") for page in cleaned[1:]] == bodies[1:]


def test_body_lines_repeated_inside_the_pages_are_kept() -> None:
    bodies = [["inicio", "ANEXO", f"texto {i}", "ANEXO", "fin " + str(i)] for i in range(6)]
    cleaned = remove_running_lines(_with_header(bodies))
    assert sum(page.split("\n").count("ANEXO") for page in cleaned) == 12


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_too_few_pages_to_judge_are_left_alone(count: int) -> None:
    """Repetition on two pages may be two notices with the same title."""
    pages = _with_header([[f"texto {i}"] for i in range(count)]) if count else []
    assert remove_running_lines(pages) == pages


def test_a_page_with_nothing_but_the_header_becomes_empty() -> None:
    bodies = [["a"], ["b"], [], ["c"], ["d"]]
    assert remove_running_lines(_with_header(bodies))[2] == ""


@pytest.mark.parametrize("seed", range(40))
def test_never_removes_body_text_of_a_generated_issue(seed: int) -> None:
    issue = generate_issue(seed, notices=random.Random(seed).randrange(1, 60))
    cleaned = remove_running_lines(issue.pages)
    assert len(cleaned) == len(issue.pages)
    for page, body in zip(cleaned[1:], issue.bodies[1:], strict=True):
        assert page.endswith("\n".join(body))
        if issue.header_pages >= 3:
            assert page == "\n".join(body)
    assert cleaned[0] == issue.pages[0]
