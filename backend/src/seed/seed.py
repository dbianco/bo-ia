"""Carga datos de ejemplo si la tabla `documentos` está vacía.

Los datos de ejemplo están shaped como llegarían de un conector del
Boletín (`sample_documentos.json`); el adaptador del Boletín los traduce
al contrato común antes de ingerirlos, igual que haría un conector real.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from src.db.models import Documento
from src.ingestor.adapters.boletin import documento_desde_boletin
from src.ingestor.contract import ingerir_documento
from src.processor.embeddings import EmbeddingProvider

SAMPLE_PATH = Path(__file__).parent / "sample_documentos.json"


def sembrar_si_vacio(session: Session, embedder: EmbeddingProvider) -> int:
    """Idempotente: no hace nada si ya hay documentos cargados. Devuelve
    la cantidad de documentos de ejemplo creados."""
    if session.query(Documento).count() > 0:
        return 0

    datos = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    creados = 0
    for item in datos:
        doc = documento_desde_boletin(
            jurisdiccion=item["jurisdiccion"],
            identificador_oficial=item["identificador_oficial"],
            fecha_publicacion=date.fromisoformat(item["fecha_publicacion"]),
            texto_original=item["texto_original"],
            url_oficial=item["url_oficial"],
            titulo=item.get("titulo"),
            metadata=item.get("metadata"),
        )
        resultado = ingerir_documento(session, embedder, doc)
        if not resultado.ya_existia:
            creados += 1

    return creados
