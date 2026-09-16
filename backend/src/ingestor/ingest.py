"""Ingestor: valida y persiste boletines de forma idempotente.

FR-001: acepta texto + identificador + fecha + URL oficial.
FR-002: la ingesta es idempotente (no duplica un mismo boletín).
FR-003: conserva una referencia al contenido original recibido.
FR-006 se cumple a nivel del endpoint de ingesta (T023), que envuelve esta
función junto con la fragmentación: un error ahí no debe perder el boletín
ya persistido acá.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Boletin


class BoletinInvalido(ValueError):
    """El boletín recibido no tiene los campos obligatorios (FR-001)."""


@dataclass
class ResultadoIngesta:
    boletin: Boletin
    ya_existia: bool


def _validar(
    *,
    jurisdiccion: str,
    identificador_oficial: str,
    fecha_publicacion: date | None,
    texto_original: str,
    url_oficial: str,
) -> None:
    faltantes = [
        nombre
        for nombre, valor in (
            ("jurisdiccion", jurisdiccion),
            ("identificador_oficial", identificador_oficial),
            ("texto_original", texto_original),
            ("url_oficial", url_oficial),
        )
        if not valor or not valor.strip()
    ]
    if fecha_publicacion is None:
        faltantes.append("fecha_publicacion")
    if faltantes:
        raise BoletinInvalido(f"Campos obligatorios faltantes: {', '.join(faltantes)}")


def _hash_contenido(texto_original: str) -> str:
    return hashlib.sha256(texto_original.encode("utf-8")).hexdigest()


def ingerir_boletin(
    session: Session,
    *,
    jurisdiccion: str,
    identificador_oficial: str,
    fecha_publicacion: date | None,
    texto_original: str,
    url_oficial: str,
    titulo: str | None = None,
) -> ResultadoIngesta:
    """Crea el boletín si no existe. Idempotente por (jurisdiccion,
    identificador_oficial) y por hash_contenido."""
    _validar(
        jurisdiccion=jurisdiccion,
        identificador_oficial=identificador_oficial,
        fecha_publicacion=fecha_publicacion,
        texto_original=texto_original,
        url_oficial=url_oficial,
    )
    hash_contenido = _hash_contenido(texto_original)

    existente = session.scalar(
        select(Boletin).where(
            (Boletin.jurisdiccion == jurisdiccion)
            & (Boletin.identificador_oficial == identificador_oficial)
        )
    )
    if existente is None:
        existente = session.scalar(select(Boletin).where(Boletin.hash_contenido == hash_contenido))

    if existente is not None:
        return ResultadoIngesta(boletin=existente, ya_existia=True)

    boletin = Boletin(
        jurisdiccion=jurisdiccion,
        identificador_oficial=identificador_oficial,
        fecha_publicacion=fecha_publicacion,
        titulo=titulo,
        texto_original=texto_original,
        url_oficial=url_oficial,
        hash_contenido=hash_contenido,
        estado_ingesta="pendiente",
    )
    session.add(boletin)
    session.flush()  # asigna id sin cerrar la transacción; el commit lo decide el llamador
    return ResultadoIngesta(boletin=boletin, ya_existia=False)
