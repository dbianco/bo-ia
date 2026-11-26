"""Generated gazette issues with known notice boundaries, laid out like the real
ones: a cover with a masthead, a table of contents that is extracted after the
body of the page, a running header with the page number, two columns, notices
that cross pages, notices published as an image (no text but the closing line),
and notices that quote the closing line of another one.

Written apart from the splitter on purpose: it shares no code with it."""
from __future__ import annotations

import random
import textwrap
from dataclasses import dataclass, field
from datetime import date, timedelta

from src.synthetic.corpus import BODIES, FILLERS, MONTHS, STREETS, SURNAMES, TOWNS
from src.synthetic.lexicon import COMPANIES, WORKS

DAYS = ("LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO")
HEADINGS = ("Licitaciones", "Subastas Electrónicas", "Convocatorias", "Compulsas Abreviadas", "Notificaciones")
MOTTO = "Año de los Derechos Humanos por la Memoria, la Verdad y la Justicia."
FIRST_PAGE_LINES = 60
PAGE_LINES = 92


@dataclass
class GeneratedNotice:
    number: str
    days: int
    last_date: date
    lines: list[str]  # including the section heading before it, if any, and the closing line
    pages: list[int] = field(default_factory=list)  # one per line

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class GeneratedIssue:
    date: date
    section: int
    pages: list[str]  # as an extractor returns them, with headers
    bodies: list[list[str]]  # body lines of each page: without running header, masthead and contents
    masthead: list[str]
    contents: list[str]
    notices: list[GeneratedNotice]
    trailing: list[str]  # text after the last closing line
    header_pages: int  # how many pages carry the running header


def _amount(rng: random.Random) -> str:
    return "s/c" if rng.random() < 0.7 else f"$ {rng.randrange(900, 99_999)},{rng.randrange(0, 100):02d}"


def _closing(rng: random.Random, days: int, number: str, last: date) -> str:
    unit = "día" if days == 1 else "días"
    line = f"{days} {unit} - Nº {number} - {_amount(rng)} - {last.day}/{last.month}/{last.year} - BOE"
    if rng.random() < 0.05:  # the extractor adds spaces around some glyph pairs
        line = line.replace("/", " /", 1)
    return line


def _sentence(rng: random.Random) -> str:
    return rng.choice(FILLERS).format(
        file=f"{rng.randrange(1, 999):04d}-{rng.randrange(10**5, 10**6)}/2026",
        h1=rng.randrange(7, 10),
        h2=rng.randrange(12, 19),
        street=rng.choice(STREETS),
        number=rng.randrange(10, 5000),
        postal=rng.randrange(5000, 6000),
        surname1=rng.choice(SURNAMES),
        surname2=rng.choice(SURNAMES),
        day=rng.randrange(1, 29),
        month=rng.choice(MONTHS),
        phone=f"351-{rng.randrange(4_000_000, 5_000_000)}",
    )


def _wrap(text: str) -> list[str]:
    return textwrap.wrap(text, 72, break_on_hyphens=False)


def _quote(rng: random.Random, issue_date: date, others: list[str]) -> list[str]:
    """Lines that quote a closing line, in the ways a notice may do it."""
    old = issue_date - timedelta(days=rng.randrange(1, 40))
    number = str(rng.randrange(500_000, 599_999))
    past = f"3 días - Nº {number} - s/c - {old.day}/{old.month}/{old.year} - BOE"
    current = f"3 días - Nº {number} - s/c - {issue_date.day}/{issue_date.month}/{issue_date.year} - BOE"
    kind = rng.randrange(5)
    if kind == 0:  # inside a sentence
        return _wrap(f"Se rectifica el aviso {current} publicado en esta misma sección, conforme lo ordenado en autos.")
    if kind == 1:  # a whole line, already expired, followed by a new sentence
        return ["Se deja sin efecto la publicación del aviso que se identifica como", past, "La presente lo reemplaza."]
    if kind == 2:  # a whole line, still running, and the sentence goes on
        return ["Se hace saber que el edicto identificado como", current, "queda rectificado en todos sus términos."]
    if kind == 3:  # a whole line between quotation marks
        return ["Donde figura el cierre “", current, "” debe leerse conforme la planilla adjunta."]
    if others:  # the number of another notice of this issue
        line = f"3 días - Nº {rng.choice(others)} - s/c - {issue_date.day}/{issue_date.month}/{issue_date.year} - BOE"
        return ["Fe de erratas. Aviso con el siguiente cierre:", line, "Corresponde la rectificación ordenada."]
    return ["Se deja sin efecto el aviso", past, "La presente lo reemplaza."]


def _notice(
    rng: random.Random, number: str, issue_date: date, heading: str | None, others: list[str], quotes: float
) -> GeneratedNotice:
    days = rng.choice((1, 2, 3, 3, 3, 5))
    last = issue_date + timedelta(days=rng.randrange(0, days))
    lines = [heading.upper()] if heading else []
    if rng.random() >= 0.12:  # otherwise an image: no text at all
        body = rng.choice(BODIES).upper()
        municipal = rng.random() < 0.15
        lines.append(f"MUNICIPALIDAD DE {rng.choice(TOWNS).upper()}" if municipal else body)
        if rng.random() < 0.4:
            lines.append("SUBSECRETARÍA DE ADMINISTRACIÓN")
        family = rng.choice((WORKS, COMPANIES))
        opening = f"{rng.choice(family.kinds).variants[0].upper()}. Objeto: {rng.choice(family.subjects).variants[0]}."
        size = rng.choice((2, 4, 8, 8, 20, 60))
        text = " ".join([opening, *(_sentence(rng) for _ in range(size))])
        body_lines = _wrap(text)
        if rng.random() < quotes:
            # Never the last lines: a closing quote right before the real one is not a notice boundary question.
            at = rng.randrange(1, len(body_lines)) if len(body_lines) > 1 else 1
            body_lines[at:at] = _quote(rng, issue_date, others)
        lines += body_lines
        if not lines[-1].endswith((".", "BOE")):
            lines[-1] += "."
        if rng.random() < 0.2:
            lines.append("ANEXO")
    lines.append(_closing(rng, days, number, last))
    return GeneratedNotice(number, days, last, lines)


def generate_issue(
    seed: int, *, notices: int = 30, section: int = 4, quotes: float = 0.15, trailing: bool | None = None
) -> GeneratedIssue:
    rng = random.Random(f"issue:{seed}:{notices}:{section}")
    issue_date = date(2026, 1, 5) + timedelta(days=rng.randrange(300))
    numbers = rng.sample(range(600_000, 699_999), notices)
    titles = sorted(rng.sample(range(len(HEADINGS)), min(notices, rng.randrange(1, 4))))
    starts = {0: HEADINGS[titles[0]]}
    for title in titles[1:]:
        starts.setdefault(rng.randrange(0, notices), HEADINGS[title])
    written: list[GeneratedNotice] = []
    for i, number in enumerate(numbers):
        others = [n.number for n in written]
        written.append(_notice(rng, str(number), issue_date, starts.get(i), others, quotes))

    tail: list[str] = []
    if trailing if trailing is not None else rng.random() < 0.2:
        tail = ["DIRECCIÓN GENERAL", *_wrap(" ".join(_sentence(rng) for _ in range(3)))]

    # Distribute the lines over the pages; columns need no trace, as they are read in content order.
    stream = [(line, notice) for notice in written for line in notice.lines] + [(line, None) for line in tail]
    bodies: list[list[str]] = [[]]
    room = FIRST_PAGE_LINES + rng.randrange(-8, 9)
    for line, notice in stream:
        if len(bodies[-1]) >= room:
            bodies.append([])
            room = PAGE_LINES + rng.randrange(-8, 9)
        bodies[-1].append(line)
        if notice is not None:
            notice.pages.append(len(bodies))

    day = f"{DAYS[issue_date.weekday()]} {issue_date.day} DE {MONTHS[issue_date.month - 1].upper()} DE {issue_date.year}"
    masthead = [
        "SUMARIO", "SECCION", "1", "BOLETIN OFICIAL DE LA PROVINCIA DE CORDOBA", "CONCESIONES, LICITACIONES, ",
        "SERVICIOS PÚBLICOS Y ", "CONTRATACIONES EN GENERAL", str(section), "a", "2026",
        "Año de los Derechos Humanos por ", "la Memoria, la Verdad y la Justicia.", day, "AÑO CXIII - TOMO DCCXLI - Nº 186",
        "CÓRDOBA, (R.A.) ", "http://boletinoficial.cba.gov.ar", "Email: boe@cba.gov.ar",
    ]
    contents = ["REDES DE ", "CONTACTO BOE"]
    for i, heading in sorted(starts.items()):
        contents.append(f"{heading} {'.' * (60 - len(heading))}Pag. {written[i].pages[0]}")
    pages = ["\n".join([*masthead, *bodies[0], *contents])]
    for i, body in enumerate(bodies[1:], start=2):
        header = [
            str(i), "BOLETIN OFICIAL DE LA PROVINCIA DE CORDOBA", "AÑO CXIII - TOMO DCCXLI - Nº 186",
            f"CORDOBA, (R.A.) {day}", f"BOLETIN OFICIAL DE LA PROVINCIA DE CÓRDOBA{section}", "a",
            "CONCESIONES, LICITACIONES, SERVICIOS PÚBLICOS Y ", "CONTRATACIONES EN GENERAL", f"2026 - {MOTTO}",
        ]
        pages.append("\n".join([*header, *body]))
    return GeneratedIssue(issue_date, section, pages, bodies, masthead, contents, written, tail, len(bodies) - 1)
