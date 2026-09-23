"""Spike descartable: compara Scrapy y Playwright sobre un día del BOP."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

URL = "https://bop.dipucordoba.es/dia/05-06-2026"
OUT = Path(__file__).with_name("resultados.json")


@dataclass
class DocumentoNormalizado:
    fuente: str
    identificador_externo: str
    fecha: date
    titulo: str
    texto: str
    url_fuente: str
    metadata: dict[str, str]


def normalizar(fecha: date, titulo: str, url: str, organismo: str) -> DocumentoNormalizado:
    identificador = re.search(r"BOP-[A-Z]-\d{4}-\d+", url)
    if not identificador:
        raise ValueError(f"URL sin identificador BOP: {url}")
    return DocumentoNormalizado(
        fuente="bop-cordoba-diputacion",
        identificador_externo=identificador.group(0),
        fecha=fecha,
        titulo=titulo,
        texto=titulo,
        url_fuente=url,
        metadata={"organismo": organismo},
    )


def _documentos(items: list[tuple[str, str, str]]) -> list[DocumentoNormalizado]:
    return [normalizar(date(2026, 6, 5), titulo, url, organismo) for titulo, url, organismo in items]


def run_scrapy() -> dict:
    from scrapy import Spider
    from scrapy.crawler import CrawlerProcess

    inicio = time.perf_counter()
    items = []
    respuestas = []

    class BopSpider(Spider):
        name = "bop_poc"
        start_urls = [URL]

        def parse(self, response):
            respuestas.append(response)
            for announcement in response.css("li.announcement"):
                titulo = " ".join(announcement.xpath("string(./p[1])").get(default="").split())
                enlace = announcement.css("a.pdf::attr(href)").get()
                organismo = " ".join(announcement.xpath("preceding::h2[1]/text()").get(default="").split())
                if titulo and enlace:
                    items.append((titulo, response.urljoin(enlace), organismo))

    process = CrawlerProcess(
        settings={"LOG_ENABLED": False, "ROBOTSTXT_OBEY": True, "RETRY_TIMES": 2}
    )
    process.crawl(BopSpider)
    process.start()
    response = respuestas[0]
    documentos = _documentos(items)
    return resultado("scrapy", inicio, response.status, documentos, response.text)


def run_playwright() -> dict:
    from playwright.sync_api import sync_playwright

    inicio = time.perf_counter()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        response = page.goto(URL, wait_until="domcontentloaded", timeout=30_000)
        items = []
        for announcement in page.locator("li.announcement").all():
            titulo = " ".join(announcement.locator("p").first.inner_text().split())
            enlace = announcement.locator("a.pdf").get_attribute("href")
            organismo = " ".join(announcement.locator("xpath=preceding::h2[1]").inner_text().split())
            if titulo and enlace:
                items.append((titulo, urljoin(URL, enlace), organismo))
        documentos = _documentos(items)
        html = page.content()
        browser.close()
    return resultado("playwright", inicio, response.status if response else 0, documentos, html)


def resultado(tool: str, inicio: float, status: int, documentos: list[DocumentoNormalizado], html: str) -> dict:
    ids = [doc.identificador_externo for doc in documentos]
    return {
        "tool": tool,
        "status_http": status,
        "duracion_segundos": round(time.perf_counter() - inicio, 3),
        "documentos": len(documentos),
        "ids_unicos": len(set(ids)),
        "idempotencia_por_identificador": len(ids) == len(set(ids)),
        "primer_documento": asdict(documentos[0]) if documentos else None,
        "hash_respuesta": hashlib.sha256(html.encode()).hexdigest(),
    }


def main() -> None:
    resultados = [run_scrapy(), run_playwright()]
    assert all(item["status_http"] == 200 for item in resultados)
    assert all(item["documentos"] > 0 for item in resultados)
    assert all(item["idempotencia_por_identificador"] for item in resultados)
    OUT.write_text(json.dumps(resultados, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps(resultados, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
