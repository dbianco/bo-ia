"""Extracción de texto de PDF para el conector del BOP (FR-007, FR-008).

Los documentos del BOP son PDFs generados digitalmente (texto real, no
escaneado); `pypdf` alcanza. Un PDF escaneado o corrupto falla acá de
forma controlada, y queda como error de ese documento puntual (no de toda
la ejecución) — ver `src/connectors/runner.py`.

Page-by-page extraction is in `src/connectors/pdf_pages.py`.
"""
from __future__ import annotations

from src.connectors.pdf_pages import ErrorExtraccionPDF, extract_pages

__all__ = ["ErrorExtraccionPDF", "extraer_texto_pdf"]


def extraer_texto_pdf(contenido: bytes) -> str:
    return "\n".join(extract_pages(contenido))
