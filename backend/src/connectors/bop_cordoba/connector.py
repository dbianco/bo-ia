"""Conector del BOP Córdoba: corre el spider en un subproceso propio y
traduce su salida al contrato común (FR-004, FR-005, FR-006).

Scrapy corre sobre el reactor de Twisted, que no se puede reiniciar
dentro de un mismo proceso — un problema real para un scheduler que
dispara la misma fuente repetidamente. Por eso cada corrida usa un
`multiprocessing.Process` (`spawn`) propio, que exporta los items a un
archivo temporal (`FEEDS`); este módulo lee ese archivo y nunca importa
`scrapy` en el proceso principal.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from multiprocessing import get_context
from pathlib import Path
from tempfile import TemporaryDirectory

from src.connectors.protocol import ErrorDescubrimiento
from src.ingestor.contract import DocumentoNormalizado

VERSION = "bop-cordoba-scrapy-v1"

TIMEOUT_DESCARGA_DEFAULT = 30
REINTENTOS_DEFAULT = 2
# Alto a propósito: en un contenedor Docker (probado en Docker Desktop),
# Scrapy/Twisted resultó mucho más lento que una petición HTTP directa
# contra el mismo sitio (~25s por documento vs ~2.5s con urllib), aunque
# la red del contenedor en sí no está degradada. Con una fuente que corre
# una vez por día (frecuencia_minutos en installation.yaml), la latencia
# no importa; perder una corrida completa por timeout, sí.
TIMEOUT_PROCESO_DEFAULT = 900


def _correr_spider(start_url: str, fecha: str, config: dict, out_path: str) -> None:
    # Import perezoso: scrapy solo se importa dentro del subproceso.
    from scrapy.crawler import CrawlerProcess

    from src.connectors.bop_cordoba.spider import BopCordobaSpider

    proceso = CrawlerProcess(
        settings={
            "LOG_ENABLED": False,
            "ROBOTSTXT_OBEY": True,
            "RETRY_TIMES": config.get("retry_times", REINTENTOS_DEFAULT),
            "DOWNLOAD_TIMEOUT": config.get("timeout_segundos", TIMEOUT_DESCARGA_DEFAULT),
            "FEEDS": {out_path: {"format": "jsonlines", "encoding": "utf8"}},
        }
    )
    proceso.crawl(BopCordobaSpider, start_url=start_url, fecha=fecha)
    proceso.start()


class ConectorBopCordoba:
    def descubrir(
        self, *, fuente_clave: str, config: dict
    ) -> Iterator[DocumentoNormalizado | ErrorDescubrimiento]:
        fecha = date.fromisoformat(config["fecha"]) if config.get("fecha") else date.today()
        start_url = config["url_template"].format(fecha=fecha.strftime("%d-%m-%Y"))

        with TemporaryDirectory() as tmp:
            out_path = str(Path(tmp) / "items.jsonl")
            contexto = get_context("spawn")
            proceso = contexto.Process(
                target=_correr_spider, args=(start_url, fecha.isoformat(), config, out_path)
            )
            proceso.start()
            proceso.join(timeout=config.get("proceso_timeout_segundos", TIMEOUT_PROCESO_DEFAULT))
            if proceso.is_alive():
                proceso.terminate()
                proceso.join()
                raise TimeoutError(f"El spider del BOP no terminó dentro del tiempo límite ({start_url})")
            if proceso.exitcode != 0:
                raise RuntimeError(f"El spider del BOP terminó con código {proceso.exitcode} ({start_url})")

            ruta = Path(out_path)
            if not ruta.exists():
                return
            for linea in ruta.read_text(encoding="utf-8").splitlines():
                if not linea.strip():
                    continue
                item = json.loads(linea)
                if item.get("error"):
                    yield ErrorDescubrimiento(
                        identificador_externo=item.get("identificador_externo"), error=item["error"]
                    )
                    continue
                yield DocumentoNormalizado(
                    fuente_clave=fuente_clave,
                    identificador_externo=item["identificador_externo"],
                    fecha=date.fromisoformat(item["fecha"]),
                    texto=item["texto"],
                    url_fuente=item["url_fuente"],
                    titulo=item.get("titulo") or None,
                    metadata=item.get("metadata") or {},
                )
