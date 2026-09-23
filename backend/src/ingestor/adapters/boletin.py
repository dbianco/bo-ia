"""Adaptador del vertical Boletín: traduce sus campos propios al contrato
común `DocumentoNormalizado` (sección 8 del design spec). Es el único
lugar del backend, junto con los datos de seed, donde puede aparecer
vocabulario específico del Boletín (FR-017)."""
from __future__ import annotations

from datetime import date

from src.ingestor.contract import DocumentoNormalizado


def documento_desde_boletin(
    *,
    jurisdiccion: str,
    identificador_oficial: str,
    fecha_publicacion: date,
    texto_original: str,
    url_oficial: str,
    titulo: str | None = None,
    metadata: dict | None = None,
) -> DocumentoNormalizado:
    return DocumentoNormalizado(
        fuente_clave=jurisdiccion,
        identificador_externo=identificador_oficial,
        fecha=fecha_publicacion,
        texto=texto_original,
        url_fuente=url_oficial,
        titulo=titulo,
        metadata=metadata or {},
    )
