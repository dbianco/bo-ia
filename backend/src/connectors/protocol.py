"""Interfaz de conector y tipos compartidos (sección 4.3 del design spec,
FR-004, FR-005). Un conector solo descubre y normaliza; no persiste ni
conoce embeddings — eso lo hace `ejecutar_conector` vía `ingerir_documento`.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from src.ingestor.contract import DocumentoNormalizado


@dataclass
class ErrorDescubrimiento:
    """Un documento que el conector no pudo normalizar (p. ej. un PDF
    ilegible). Se cuenta como error de la ejecución sin abortarla (FR-003,
    FR-008)."""

    identificador_externo: str | None
    error: str


class Conector(Protocol):
    def descubrir(
        self, *, fuente_clave: str, config: dict
    ) -> Iterable[DocumentoNormalizado | ErrorDescubrimiento] | Iterator[DocumentoNormalizado | ErrorDescubrimiento]: ...


@runtime_checkable
class Resegmenter(Protocol):
    """A connector that can split documents stored before it produced notices."""

    def resegment(
        self, *, fuente_clave: str, identifier: str, issue_date: date, text: str, url: str, refetch_config: dict | None
    ) -> list[DocumentoNormalizado] | None: ...
