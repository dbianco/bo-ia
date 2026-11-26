"""Fusión de rankings (Reciprocal Rank Fusion) para la búsqueda híbrida
(texto exacto + similitud vectorial). Ver sección 8 del design spec.

RRF combina listas ordenadas cuyas puntuaciones no son comparables entre
sí (similitud coseno 0-1 vs. `ts_rank` de Postgres, en escalas distintas)
sin necesidad de normalizarlas: cada item suma 1/(k + posición) por cada
lista en la que aparece.
"""
from __future__ import annotations

from collections.abc import Sequence

RRF_K = 60  # constante estándar de RRF (Cormack et al., 2009)


def fusionar_rrf(*listas_de_ids: list[int], pesos: Sequence[float] | None = None) -> dict[int, float]:
    """Combina varias listas ya ordenadas por relevancia (de mayor a
    menor) de un mismo identificador en un único score RRF por
    identificador. Un item ausente de una lista simplemente no suma esa
    contribución. Cuanto más alto el score, más relevante.

    `pesos`, one per list, multiply what each list adds (1 by default)."""
    scores: dict[int, float] = {}
    for lista, peso in zip(listas_de_ids, pesos or [1.0] * len(listas_de_ids), strict=True):
        for posicion, item_id in enumerate(lista):
            scores[item_id] = scores.get(item_id, 0.0) + peso / (RRF_K + posicion + 1)
    return scores
