"""Conector del dataset abierto de convocatorias nacionales de
comprar.gob.ar (sección 4.6/8 del design spec, Etapa 5, FR-001 a FR-004).

El sitio en vivo (comprar.gob.ar) es ASP.NET WebForms con postbacks
(`__VIEWSTATE`), frágil para scrapear. En cambio, el mismo dataset se
publica como CSV abierto en datos.gob.ar (`Convocatorias.csv`,
actualizado semestralmente) — este conector lo descarga y lo procesa en
streaming, sin sumar ninguna dependencia (`urllib`/`csv`, librería
estándar).
"""
from __future__ import annotations

import csv
import logging
from collections.abc import Iterator
from datetime import date
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.connectors.protocol import ErrorDescubrimiento
from src.ingestor.contract import DocumentoNormalizado

VERSION = "comprar-gob-ar-csv-v1"

TIMEOUT_DEFAULT = 60
USER_AGENT = "bo-ia-connector/1.0"

# comprar.gob.ar no expone una URL de detalle estable por proceso (ver
# spec.md, Research): se usa la página del dataset abierto como
# `url_fuente` para todos los documentos, una limitación conocida.
URL_FUENTE_DATASET = "https://www.datos.gob.ar/dataset/sistema-de-contrataciones-electronicas"

logger = logging.getLogger("bo-ia.connectors.comprar_gob_ar")


def _parsear_fecha(valor: str) -> date:
    # "03/03/2017 08:00:00 p.m." -> solo la parte de fecha, dd/mm/aaaa.
    parte_fecha = valor.split(" ", 1)[0]
    dia, mes, anio = parte_fecha.split("/")
    return date(int(anio), int(mes), int(dia))


def _parsear_monto(valor: str) -> float | None:
    valor = valor.strip()
    if not valor:
        return None
    try:
        return float(valor.replace(",", ""))
    except ValueError:
        return None


def _fila_a_documento(fuente_clave: str, fila: dict) -> DocumentoNormalizado:
    metadata: dict = {
        "organismo": fila["Descripcion_SAF"],
        "jurisdiccion": "nacional",
    }
    monto = _parsear_monto(fila["Monto_Estimado"])
    if monto is not None:
        metadata["monto"] = monto

    titulo = fila["Nombre_del_Proceso"]
    objeto = fila["Objeto_del_Proceso"]
    texto = titulo if titulo == objeto else f"{titulo}\n\n{objeto}"

    return DocumentoNormalizado(
        fuente_clave=fuente_clave,
        identificador_externo=fila["Numero_Proceso"],
        fecha=_parsear_fecha(fila["Fecha_de_Publicacion"]),
        texto=texto,
        url_fuente=URL_FUENTE_DATASET,
        titulo=titulo,
        metadata=metadata,
    )


class ConectorComprarGobAr:
    def descubrir(
        self, *, fuente_clave: str, config: dict
    ) -> Iterator[DocumentoNormalizado | ErrorDescubrimiento]:
        csv_url = config["csv_url"]
        anio_desde = config.get("anio_desde")
        timeout = config.get("timeout_segundos", TIMEOUT_DEFAULT)
        # `Convocatorias.csv` cubre todo el país; un `anio_desde` reciente
        # puede igual matchear miles de filas (confirmado en una corrida
        # real: 2026 solo ya superó las 5000). `limite_filas` acota una
        # corrida — sin límite por defecto (comportamiento sin cambios),
        # pero recomendado en producción y usado por la verificación real
        # de esta etapa para no correr sin límite contra el dataset real.
        limite_filas = config.get("limite_filas")

        peticion = Request(csv_url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(peticion, timeout=timeout) as respuesta:  # noqa: S310 (URL de config, no de usuario)
                lineas = (linea.decode("utf-8") for linea in respuesta)
                lector = csv.DictReader(lineas)
                producidas = 0
                for fila in lector:
                    if limite_filas is not None and producidas >= limite_filas:
                        break
                    if anio_desde is not None:
                        try:
                            ejercicio = int(fila["Ejercicio"])
                        except (KeyError, ValueError):
                            ejercicio = None
                        if ejercicio is not None and ejercicio < anio_desde:
                            continue
                    producidas += 1
                    try:
                        yield _fila_a_documento(fuente_clave, fila)
                    except (KeyError, ValueError) as exc:
                        yield ErrorDescubrimiento(
                            identificador_externo=fila.get("Numero_Proceso"), error=str(exc)
                        )
        except URLError as exc:
            raise RuntimeError(f"No se pudo descargar el CSV de convocatorias ({csv_url}): {exc}") from exc
