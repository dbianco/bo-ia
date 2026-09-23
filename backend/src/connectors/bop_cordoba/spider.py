"""Spider de Scrapy para el Boletín Oficial de la Provincia de Córdoba
(Diputación). Descubre anuncios en la página de un día, sigue el link al
PDF de cada uno con el downloader propio de Scrapy (retry/timeout
centralizados, FR-009) y extrae su texto (FR-006, FR-007, FR-008).

Corre siempre dentro de un subproceso aparte (ver
`src/connectors/bop_cordoba/connector.py`) — nunca se importa `scrapy`
fuera de ese subproceso ni del propio spider.
"""
from __future__ import annotations

import re

import scrapy

from src.connectors.bop_cordoba.pdf import ErrorExtraccionPDF, extraer_texto_pdf

IDENTIFICADOR_RE = re.compile(r"([A-Za-z0-9_-]+)\.pdf$")


class BopCordobaSpider(scrapy.Spider):
    name = "bop_cordoba"

    def __init__(self, start_url: str, fecha: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.start_urls = [start_url]
        self._fecha = fecha

    def parse(self, response):
        for announcement in response.css("li.announcement"):
            titulo = " ".join(announcement.xpath("string(./p[1])").get(default="").split())
            enlace = announcement.css("a.pdf::attr(href)").get()
            organismo = " ".join(announcement.xpath("preceding::h2[1]/text()").get(default="").split())
            if not (titulo and enlace):
                continue

            url_pdf = response.urljoin(enlace)
            match = IDENTIFICADOR_RE.search(url_pdf)
            identificador = match.group(1) if match else url_pdf

            yield response.follow(
                url_pdf,
                callback=self.parse_pdf,
                errback=self.manejar_error_pdf,
                meta={
                    "titulo": titulo,
                    "organismo": organismo,
                    "url_pdf": url_pdf,
                    "identificador_externo": identificador,
                },
            )

    def parse_pdf(self, response):
        meta = response.meta
        try:
            texto = extraer_texto_pdf(response.body)
        except ErrorExtraccionPDF as exc:
            yield {"error": str(exc), "identificador_externo": meta["identificador_externo"]}
            return

        yield {
            "identificador_externo": meta["identificador_externo"],
            "fecha": self._fecha,
            "titulo": meta["titulo"],
            "texto": texto,
            "url_fuente": meta["url_pdf"],
            "metadata": {"organismo": meta["organismo"]} if meta["organismo"] else {},
        }

    def manejar_error_pdf(self, failure):
        meta = failure.request.meta
        yield {"error": str(failure.value), "identificador_externo": meta.get("identificador_externo")}
