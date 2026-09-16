"""Carga datos de ejemplo si la tabla `boletines` está vacía (FR-017)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from src.db.models import Boletin, Fragmento
from src.ingestor.fragmenter import fragmentar_texto
from src.ingestor.ingest import ingerir_boletin
from src.processor.embeddings import EmbeddingProvider

SAMPLE_PATH = Path(__file__).parent / "sample_boletines.json"


def sembrar_si_vacio(session: Session, embedder: EmbeddingProvider) -> int:
    """Idempotente: no hace nada si ya hay boletines cargados. Devuelve
    la cantidad de boletines de ejemplo creados."""
    if session.query(Boletin).count() > 0:
        return 0

    datos = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    creados = 0
    for item in datos:
        resultado = ingerir_boletin(
            session,
            jurisdiccion=item["jurisdiccion"],
            identificador_oficial=item["identificador_oficial"],
            fecha_publicacion=date.fromisoformat(item["fecha_publicacion"]),
            texto_original=item["texto_original"],
            url_oficial=item["url_oficial"],
            titulo=item.get("titulo"),
        )
        if resultado.ya_existia:
            continue

        boletin = resultado.boletin
        for posicion, texto in enumerate(fragmentar_texto(item["texto_original"])):
            session.add(
                Fragmento(
                    boletin_id=boletin.id,
                    posicion=posicion,
                    texto=texto,
                    fecha_publicacion=boletin.fecha_publicacion,
                    embedding=embedder.embed_passage(texto),
                )
            )
        boletin.estado_ingesta = "completo"
        creados += 1

    session.commit()
    return creados
