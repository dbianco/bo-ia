"""Filtro de umbral de similitud (FR-015, REQ-12).

Umbral interno del servicio, configurable, no expuesto al usuario ni en
la API pública. Se filtra por resultado, no por consulta completa: se
descartan los fragmentos por debajo del umbral antes de aplicar el
límite de cantidad (FR-013).
"""
from __future__ import annotations

import os
from typing import Protocol, TypeVar

UMBRAL_DEFAULT = 0.5


class _TieneSimilitud(Protocol):
    similitud: float


T = TypeVar("T", bound=_TieneSimilitud)


def umbral_configurado() -> float:
    return float(os.environ.get("SIMILARITY_THRESHOLD", UMBRAL_DEFAULT))


def filtrar_por_umbral(resultados: list[T], *, umbral: float | None = None) -> list[T]:
    """Descarta los resultados cuya `similitud` esté por debajo del
    umbral. Conserva el orden de entrada (se espera una lista ya
    ordenada por relevancia)."""
    umbral_efectivo = umbral if umbral is not None else umbral_configurado()
    return [r for r in resultados if r.similitud >= umbral_efectivo]
