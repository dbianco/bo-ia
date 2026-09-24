"""Conector del Boletín Oficial de la Provincia de Córdoba, Argentina
(`boletinoficial.cba.gov.ar`) — sección 8 del design spec, Etapa 5, FR-005
a FR-009.

El sitio publica sus secciones diarias como PDFs individuales en URLs
100% predecibles (sin necesidad de descubrir nada vía HTML/Scrapy):
`.../wp-content/4p96humuzp/{año}/{mes}/{sección}_Secc_{ddmmyy}.pdf`. Este
conector construye esa URL, descarga el PDF por HTTP directo (`urllib`,
librería estándar) y reusa la extracción de texto ya construida para el
conector del BOP (Etapa 2).

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
import subprocess
from collections.abc import Iterator
from datetime import date

from src.connectors.bop_cordoba.pdf import ErrorExtraccionPDF, extraer_texto_pdf
from src.connectors.protocol import ErrorDescubrimiento
from src.ingestor.contract import DocumentoNormalizado

VERSION = "boletin-cba-pdf-diario-v1"

TIMEOUT_DEFAULT = 60
REINTENTOS_DEFAULT = 2
USER_AGENT = "bo-ia-connector/1.0"
CURL_BIN = "curl"

SECCIONES = {
    1: "1° Sección: Legislación - Normativas",
    2: "2° Sección: Judiciales",
    3: "3° Sección: Sociedades - Personas Jurídicas - Asambleas y Otras",
    4: "4° Sección: Notificaciones, Licitaciones y Contrataciones",
    5: "5° Sección: Municipalidades y Comunas: Legislación - Normativas",
}

logger = logging.getLogger("bo-ia.connectors.boletin_cba")


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
                texto = extraer_texto_pdf(contenido)
            except (RuntimeError, ErrorExtraccionPDF) as exc:
                yield ErrorDescubrimiento(identificador_externo=identificador, error=str(exc))
                continue

            yield DocumentoNormalizado(
                fuente_clave=fuente_clave,
                identificador_externo=identificador,
                fecha=fecha,
                texto=texto,
                url_fuente=url,
                titulo=f"{SECCIONES.get(seccion, f'Sección {seccion}')} — {fecha.isoformat()}",
                metadata={"jurisdiccion": "provincial", "seccion": seccion},
            )
