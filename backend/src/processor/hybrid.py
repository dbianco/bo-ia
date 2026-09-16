"""Fusión de rankings (Reciprocal Rank Fusion) para la búsqueda híbrida
(texto exacto + similitud vectorial). Ver sección 8 del design spec.

RRF combina listas ordenadas cuyas puntuaciones no son comparables entre
sí (similitud coseno 0-1 vs. `ts_rank` de Postgres, en escalas distintas)
sin necesidad de normalizarlas: cada item suma 1/(k + posición) por cada
lista en la que aparece.
"""
from __future__ import annotations

RRF_K = 60  # constante estándar de RRF (Cormack et al., 2009)


def fusionar_rrf(*listas_de_ids: list[int]) -> dict[int, float]:
    """Combina varias listas ya ordenadas por relevancia (de mayor a
    menor) de un mismo identificador en un único score RRF por
    identificador. Un item ausente de una lista simplemente no suma esa
    contribución. Cuanto más alto el score, más relevante."""
    scores: dict[int, float] = {}
    for lista in listas_de_ids:
        for posicion, item_id in enumerate(lista):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (RRF_K + posicion + 1)
    return scores
