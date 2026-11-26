"""Plan 7: one segment per notice, and no text lost."""
import random
from datetime import date
from pathlib import Path

import pytest

from src.connectors.boletin_cba.segmenter import parse_closing, segment
from src.connectors.pdf_pages import extract_pages, remove_running_lines
from src.synthetic.issues import generate_issue

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "boletin_cba" / "4_Secc_sample.pdf"
ISSUE = date(2026, 9, 24)

# Counted on the rendered pages of the PDF, not from its text: notices that END on each page.
NOTICES_PER_PAGE = [2, 5, 6, 5, 6, 3, 5, 3]
IMAGE_NOTICES = {"688662", "688923", "689003", "688984", "688988", "688448"}
CROSSING_PAGES = {"688872": (1, 2), "688769": (4, 5), "688003": (6, 7), "687368": (7, 8)}


@pytest.fixture(scope="module")
def real():
    return segment(remove_running_lines(extract_pages(FIXTURE.read_bytes())), ISSUE)


def _rebuild(segmentation) -> str:
    spans = sorted(span for part in segmentation.parts for span in part.spans)
    assert all(a[1] == b[0] for a, b in zip(spans, spans[1:], strict=False)), "gaps or overlaps"
    return "".join(segmentation.text[start:end] for start, end in spans)


def closing(number: int = 688209, when: str = "24/9/2026") -> str:
    return f"3 días - Nº {number} - s/c - {when} - BOE"


# --- Closing line ---


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("3 días - Nº 688209 - s/c - 24/9/2026 - BOE", ("688209", 3, date(2026, 9, 24))),
        ("1 día - Nº 688992 - s/c - 24/9/2026 - BOE", ("688992", 1, date(2026, 9, 24))),
        ("3 días - Nº 688718 - $ 18273,60 - 25/9/2026 - BOE", ("688718", 3, date(2026, 9, 25))),
        ("  2 dias - N° 689003 - S/C - 05/10/2026 - BOE  ", ("689003", 2, date(2026, 10, 5))),
        ("5 días – Nº 687 583 – $ 1.593.837 ,50 – 27 /9/2026 – BOE", ("687583", 5, date(2026, 9, 27))),
    ],
)
def test_reads_number_days_and_date(line: str, expected: tuple) -> None:
    found = parse_closing(line)
    assert (found.number, found.days, found.last_date) == expected


@pytest.mark.parametrize(
    "line",
    [
        "",
        "el aviso 3 días - Nº 688209 - s/c - 24/9/2026 - BOE",
        "3 días - Nº 688209 - s/c - 24/9/2026 - BOE, publicado ayer",
        "3 días - Nº 688209 - s/c - 31/2/2026 - BOE",
        "3 días - Nº - s/c - 24/9/2026 - BOE",
        "Nº 688209 - s/c - 24/9/2026 - BOE",
        "CONTACTO BOE",
    ],
)
def test_other_lines_are_not_closing_lines(line: str) -> None:
    assert parse_closing(line) is None


# --- The real PDF ---


def test_real_pdf_has_the_number_of_notices_counted_by_eye(real) -> None:
    assert len(real.notices) == sum(NOTICES_PER_PAGE) == 35
    per_page = [0] * 8
    for notice in real.notices:
        per_page[notice.last_page - 1] += 1
    assert per_page == NOTICES_PER_PAGE


def test_real_pdf_loses_no_text(real) -> None:
    assert _rebuild(real) == real.text == "\n".join(remove_running_lines(extract_pages(FIXTURE.read_bytes())))


def test_real_pdf_notices_have_the_pages_seen_on_the_rendered_pdf(real) -> None:
    pages = {n.number: (n.first_page, n.last_page) for n in real.notices}
    assert {number: span for number, span in pages.items() if span[0] != span[1]} == CROSSING_PAGES
    assert pages["688404"] == (1, 1) and pages["687583"] == (8, 8)


def test_real_pdf_contents_and_masthead_are_apart_from_the_notices(real) -> None:
    assert "Email: boe@cba.gov.ar" in real.front_matter.text
    assert "Subastas Electrónicas ......" in real.front_matter.text
    assert not any("Pag. 7" in n.text or "SUMARIO" in n.text for n in real.notices)
    # The notice that surrounds the contents continues on the next page without them.
    crossing = next(n for n in real.notices if n.number == "688872")
    assert "Subsecretaria de Compras, \nPresupuesto e Inversiones" in crossing.text
    assert real.unsegmented is None


def test_real_pdf_image_notices_keep_only_the_closing_line(real) -> None:
    short = {n.number for n in real.notices if len(n.text.strip().split("\n")) <= 2}
    assert short == IMAGE_NOTICES


def test_real_pdf_titles(real) -> None:
    headings = {n.number: n.heading for n in real.notices}
    assert headings["688404"] == "MINISTERIO DE SEGURIDAD"  # not the section heading "LICITACIONES"
    assert headings["688627"] == "POLICÍA DE LA PROVINCIA"
    assert headings["687583"] == "UNIDAD EJECUTORA LEY 9150"
    assert headings["688448"] is None


# --- Rules ---


def test_each_notice_ends_at_its_closing_line() -> None:
    result = segment([f"A\nuno\n{closing(1001)}\nB\ndos\n{closing(1002)}"], ISSUE)
    assert [n.text for n in result.notices] == [f"A\nuno\n{closing(1001)}\n", f"B\ndos\n{closing(1002)}"]
    assert result.front_matter is None and result.unsegmented is None


def test_a_section_without_closing_lines_is_one_unsegmented_document() -> None:
    pages = ["DECRETO 1\nVisto y considerando", "Artículo 1\nPublíquese"]
    result = segment(pages, ISSUE)
    assert result.notices == []
    assert result.unsegmented.text == "\n".join(pages)
    assert (result.unsegmented.first_page, result.unsegmented.last_page) == (1, 2)


def test_text_after_the_last_closing_line_is_unsegmented() -> None:
    result = segment([f"A\nuno\n{closing()}\nAviso sin cierre\nque no debe perderse"], ISSUE)
    assert result.unsegmented.text == "Aviso sin cierre\nque no debe perderse"
    assert _rebuild(result) == result.text


def test_blank_text_after_the_last_closing_line_is_not_a_document() -> None:
    result = segment([f"A\n{closing()}\n", "", "\n"], ISSUE)
    assert result.unsegmented is None
    assert _rebuild(result) == result.text


@pytest.mark.parametrize("pages", [[], [""], ["", " \n "]])
def test_no_text_gives_no_documents(pages) -> None:
    assert segment(pages, ISSUE).parts == []


def test_a_notice_over_three_pages() -> None:
    result = segment(["A\nuno", "dos", f"tres\n{closing()}"], ISSUE)
    (notice,) = result.notices
    assert (notice.first_page, notice.last_page) == (1, 3)
    assert [(notice.text[offset:][:3], page) for offset, page in notice.page_starts] == [("A\nu", 1), ("dos", 2), ("tre", 3)]


def test_a_closing_line_alone_on_the_next_page_belongs_to_its_notice() -> None:
    result = segment(["A\nuno", f"{closing(1)}\nB\n{closing(2)}"], ISSUE)
    assert [(n.number, n.first_page, n.last_page) for n in result.notices] == [("1", 1, 2), ("2", 2, 2)]


def test_a_closing_line_broken_in_two() -> None:
    result = segment(["A\nuno\n3 días - Nº 688209 - $ 18.273,60 -\n24/9/2026 - BOE\nB\ndos\n" + closing(2)], ISSUE)
    assert [n.number for n in result.notices] == ["688209", "2"]


@pytest.mark.parametrize(
    "quoted",
    [
        f"según el aviso {closing(1)} del registro",
        f"Se deja sin efecto el aviso\n{closing(1, '20/9/2026')}\nLa presente lo reemplaza.",
        f"El edicto identificado como\n{closing(1)}\nqueda rectificado.",
        f"Donde figura “\n{closing(1)}\n” debe leerse otro.",
        f"Publicado como,\n{closing(1)}\nEl Directorio.",
    ],
    ids=["inside a sentence", "already expired", "the sentence goes on", "between quotes", "after a comma"],
)
def test_a_quoted_closing_line_does_not_split(quoted: str) -> None:
    result = segment([f"A\n{quoted}\nTexto final.\n{closing(9)}\nB\n{closing(10)}"], ISSUE)
    assert [n.number for n in result.notices] == ["9", "10"]
    assert _rebuild(result) == result.text


def test_an_erratum_that_quotes_a_notice_of_the_same_issue() -> None:
    text = f"A\nuno.\n{closing(1)}\nB\nDonde dice:\n{closing(1)}\nDebe decir otra cosa.\n{closing(2)}"
    assert [n.number for n in segment([text], ISSUE).notices] == ["1", "2"]


def test_a_notice_that_ends_with_a_colon_before_an_image_is_split() -> None:
    text = f"A\nSe publica el siguiente listado:\n{closing(1)}\nB\ndos\n{closing(2)}"
    assert [n.number for n in segment([text], ISSUE).notices] == ["1", "2"]


def test_the_town_of_a_municipal_notice() -> None:
    def town(heading: str):
        return segment([f"{heading}\nOrdenanza 1.\n{closing()}"], ISSUE).notices[0].town

    assert town("MUNICIPALIDAD DE CARLOS PAZ") == "Carlos Paz"
    assert town("MUNICIPALIDAD DE LA CIUDAD DE RÍO CUARTO.") == "Río Cuarto"
    assert town("COMUNA DE LOS CHAÑARITOS") == "Los Chañaritos"
    assert town("MUNICIPALIDAD DE VILLA SANTA CRUZ DEL LAGO") == "Villa Santa Cruz del Lago"
    assert town("MINISTERIO DE SALUD") is None
    assert town("LA MUNICIPALIDAD DE CÓRDOBA LLAMA A CONCURSO") is None


# --- Generated issues ---


def _boundaries(items) -> list[tuple[str, str]]:
    """A boundary is the closing line's number and the line before it."""
    found = []
    for number, text in items:
        lines = [line for line in text.rstrip("\n").split("\n") if line.strip()]
        found.append((number, lines[-2] if len(lines) > 1 else ""))
    return found


def test_boundary_precision_and_recall_on_generated_issues() -> None:
    hits = expected_total = found_total = 0
    for seed in range(150):
        issue = generate_issue(seed, notices=random.Random(seed).randrange(1, 80), quotes=0.3)
        result = segment(remove_running_lines(issue.pages), issue.date)
        expected = _boundaries((n.number, n.text) for n in issue.notices)
        found = _boundaries((n.number, n.text) for n in result.notices)
        hits += len(set(expected) & set(found))
        expected_total += len(expected)
        found_total += len(found)
        assert _rebuild(result) == result.text
    assert expected_total > 4000
    assert hits / found_total >= 0.99, "precision"
    assert hits / expected_total >= 0.99, "recall"


@pytest.mark.parametrize("seed", range(30))
def test_generated_notices_have_the_exact_text_and_pages(seed: int) -> None:
    issue = generate_issue(1000 + seed, notices=40, quotes=0.0)
    assert issue.header_pages >= 3
    result = segment(remove_running_lines(issue.pages), issue.date)
    assert [n.text.rstrip("\n") for n in result.notices] == [n.text for n in issue.notices]
    assert [(n.first_page, n.last_page) for n in result.notices] == [(n.pages[0], n.pages[-1]) for n in issue.notices]
    assert [(n.days, n.last_date) for n in result.notices] == [(n.days, n.last_date) for n in issue.notices]
    assert set(result.front_matter.text.split("\n")) - {""} == set(issue.masthead + issue.contents)
    trailing = result.unsegmented.text if result.unsegmented else ""
    assert trailing.strip("\n") == "\n".join(issue.trailing)
