"""Extracción de texto de PDF para el conector del BOP (FR-007, FR-008).

Los documentos del BOP son PDFs generados digitalmente (texto real, no
escaneado); `pypdf` alcanza. Un PDF escaneado o corrupto falla acá de
forma controlada, y queda como error de ese documento puntual (no de toda
la ejecución) — ver `src/connectors/runner.py`.
"""
from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class ErrorExtraccionPDF(RuntimeError):
    """El PDF no se pudo leer o no tiene texto extraíble."""


def extraer_texto_pdf(contenido: bytes) -> str:
    try:
        lector = PdfReader(io.BytesIO(contenido))
        texto = "\n".join(pagina.extract_text() or "" for pagina in lector.pages)
    except (PdfReadError, ValueError) as exc:
        raise ErrorExtraccionPDF(f"No se pudo leer el PDF: {exc}") from exc

    if not texto.strip():
        raise ErrorExtraccionPDF("El PDF no tiene texto extraíble (¿está escaneado?)")
    return texto
