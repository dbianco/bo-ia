"""Conector del Boletín Oficial de la Provincia de Córdoba, Argentina
(`boletinoficial.cba.gov.ar`) — sección 8 del design spec, Etapa 5, FR-005
a FR-009.

El sitio publica sus secciones diarias como PDFs individuales en URLs
100% predecibles (sin necesidad de descubrir nada vía HTML/Scrapy):
`.../wp-content/4p96humuzp/{año}/{mes}/{sección}_Secc_{ddmmyy}.pdf`. Este
conector construye esa URL, descarga el PDF y lo separa en avisos.

Each notice is a document of its own, with its number and pages (see
`segmenter.py`). What is in no notice is kept too: the cover and table of
contents as one document that is not searchable, and any text without a closing
line as an explicit "unsegmented" document.

`boletinoficial.cba.gov.ar/robots.txt` bloquea por nombre a `ClaudeBot` y
otros bots de IA, pero no a crawlers genéricos en rutas de contenido
(decisión ya tomada en spec.md) — por eso se declara un User-Agent
descriptivo propio, no el default de `urllib` ni un nombre bloqueado.

La descarga usa `curl` como subproceso, no `urllib`: el sitio corre
detrás de CloudFront y devuelve 403 a peticiones de `urllib` (mismo
User-Agent, mismos headers) mientras que `curl` recibe 200 — casi
seguro por diferencias de fingerprint TLS/HTTP2 entre ambos clientes, no
por el User-Agent. `curl` ya está disponible en la imagen del backend;
no es una dependencia de Python nueva.
"""
from __future__ import annotations

import logging
import re
import subprocess
from collections import Counter
from collections.abc import Iterator
from datetime import date

from src.connectors.boletin_cba.segmenter import Segment, Segmentation, segment
from src.connectors.pdf_pages import ErrorExtraccionPDF, extract_pages, remove_running_lines
from src.connectors.protocol import ErrorDescubrimiento
from src.ingestor.contract import DocumentoNormalizado

VERSION = "boletin-cba-pdf-diario-v2"
METADATA_KEYS = frozenset({"jurisdiccion", "seccion", "municipio", "publication_days", "last_publication_date"})

TIMEOUT_DEFAULT = 60
REINTENTOS_DEFAULT = 2
USER_AGENT = "contextcrawl-connector/1.0"
CURL_BIN = "curl"

SECCIONES = {
    1: "1° Sección: Legislación - Normativas",
    2: "2° Sección: Judiciales",
    3: "3° Sección: Sociedades - Personas Jurídicas - Asambleas y Otras",
    4: "4° Sección: Notificaciones, Licitaciones y Contrataciones",
    5: "5° Sección: Municipalidades y Comunas: Legislación - Normativas",
}

logger = logging.getLogger("contextcrawl.connectors.boletin_cba")


def construir_url(url_template: str, *, seccion: int, fecha: date) -> str:
    return url_template.format(
        seccion=seccion,
        anio=fecha.strftime("%Y"),
        mes=fecha.strftime("%m"),
        ddmmyy=fecha.strftime("%d%m%y"),
    )


def _descargar(url: str, *, timeout: int, reintentos: int) -> bytes:
    ultimo_error: str | None = None
    for _intento in range(reintentos + 1):
        resultado = subprocess.run(  # noqa: S603 (URL de config, no de usuario; sin shell=True)
            [CURL_BIN, "-sS", "--fail", "--max-time", str(timeout), "-A", USER_AGENT, url],
            capture_output=True,
            check=False,
        )
        if resultado.returncode == 0:
            return resultado.stdout
        ultimo_error = resultado.stderr.decode("utf-8", errors="replace").strip()
    raise RuntimeError(f"No se pudo descargar {url}: {ultimo_error}")


# Identifier of a document that is a whole section, from before the notices were split.
_SECTION_IDENTIFIER = re.compile(r"(\d+)_Secc_\d{6}")
MAX_TITLE = 200


def _documents(
    segmentation: Segmentation,
    *,
    fuente_clave: str,
    identifier: str,
    section: int,
    issue_date: date,
    url: str,
    with_pages: bool,
) -> Iterator[DocumentoNormalizado]:
    section_title = SECCIONES.get(section, f"Sección {section}")

    def document(part: Segment, suffix: str, title: str, **fields) -> DocumentoNormalizado:
        metadata = {"jurisdiccion": "provincial", "seccion": section, **fields.pop("metadata", {})}
        return DocumentoNormalizado(
            fuente_clave=fuente_clave,
            identificador_externo=f"{identifier}_{suffix}",
            fecha=issue_date,
            texto=part.text,
            url_fuente=f"{url}#page={part.first_page}" if with_pages else url,
            titulo=title,
            metadata=metadata,
            issue=identifier,
            page_starts=part.page_starts if with_pages else [],
            **fields,
        )

    if segmentation.front_matter is not None:
        title = f"Portada y sumario — {section_title} — {issue_date.isoformat()}"
        yield document(segmentation.front_matter, "cover", title, searchable=False)

    seen: Counter[str] = Counter()
    for notice in segmentation.notices:
        seen[notice.number] += 1
        repetition = f"-{seen[notice.number]}" if seen[notice.number] > 1 else ""
        metadata: dict = {
            "publication_days": notice.days,
            "last_publication_date": notice.last_date.isoformat(),
        }
        if notice.town:
            metadata["municipio"] = notice.town
        yield document(
            notice,
            f"N{notice.number}{repetition}",
            f"Aviso Nº {notice.number} — {notice.heading or section_title}"[:MAX_TITLE],
            notice_number=notice.number,
            metadata=metadata,
        )

    if segmentation.unsegmented is not None:
        yield document(segmentation.unsegmented, "unsegmented", f"{section_title} — {issue_date.isoformat()}")


def _pages_of_saved_text(text: str) -> list[str]:
    """Cuts a text that was saved without pages where a running header with the
    page number appears, so that the headers can be removed. It is not evidence
    enough to cite a page."""
    lines = text.split("\n")
    numbers = [i for i in range(len(lines) - 1) if lines[i].strip().isdigit()]
    if not numbers:
        return [text]
    after = Counter(lines[i + 1].strip() for i in numbers)
    header, times = after.most_common(1)[0]
    cuts, expected = [], 2
    for i in numbers:
        if lines[i].strip() == str(expected) and lines[i + 1].strip() == header:
            cuts.append(i)
            expected += 1
    if times < 2 or not cuts:
        return [text]
    starts = [0, *cuts]
    return ["\n".join(lines[a:b]) for a, b in zip(starts, [*cuts, len(lines)], strict=True)]


class ConectorBoletinCba:
    def descubrir(
        self, *, fuente_clave: str, config: dict
    ) -> Iterator[DocumentoNormalizado | ErrorDescubrimiento]:
        url_template = config["url_template"]
        secciones: list[int] = config["secciones"]
        fecha = date.fromisoformat(config["fecha"]) if config.get("fecha") else date.today()
        timeout = config.get("timeout_segundos", TIMEOUT_DEFAULT)
        reintentos = config.get("reintentos", REINTENTOS_DEFAULT)

        for seccion in secciones:
            identificador = f"{seccion}_Secc_{fecha.strftime('%d%m%y')}"
            url = construir_url(url_template, seccion=seccion, fecha=fecha)
            try:
                contenido = _descargar(url, timeout=timeout, reintentos=reintentos)
                paginas = extract_pages(contenido)
            except (RuntimeError, ErrorExtraccionPDF) as exc:
                yield ErrorDescubrimiento(identificador_externo=identificador, error=str(exc))
                continue

            yield from _documents(
                segment(remove_running_lines(paginas), fecha),
                fuente_clave=fuente_clave,
                identifier=identificador,
                section=seccion,
                issue_date=fecha,
                url=url,
                with_pages=True,
            )

    def resegment(
        self, *, fuente_clave: str, identifier: str, issue_date: date, text: str, url: str, refetch_config: dict | None
    ) -> list[DocumentoNormalizado] | None:
        """The documents inside one that was stored as a whole section; None if
        it is not one. With `refetch_config`, the configuration of the source,
        the PDF is downloaded again, which gives the pages; it raises if that
        fails. The address is built from the configuration and never taken from
        the stored document, which may have been posted by anyone."""
        match = _SECTION_IDENTIFIER.fullmatch(identifier)
        if match is None:
            return None
        section = int(match[1])
        if refetch_config is not None:
            url = construir_url(refetch_config["url_template"], seccion=section, fecha=issue_date)
            content = _descargar(url, timeout=TIMEOUT_DEFAULT, reintentos=REINTENTOS_DEFAULT)
            pages = extract_pages(content)
        else:
            pages = _pages_of_saved_text(text)
        return list(
            _documents(
                segment(remove_running_lines(pages), issue_date),
                fuente_clave=fuente_clave,
                identifier=identifier,
                section=section,
                issue_date=issue_date,
                url=url,
                with_pages=refetch_config is not None,
            )
        )
