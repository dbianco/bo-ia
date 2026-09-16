"""Tests de la fusión Reciprocal Rank Fusion (RRF) para búsqueda híbrida."""
from src.processor.hybrid import fusionar_rrf


def test_fusionar_rrf_favorece_items_que_aparecen_en_ambas_listas() -> None:
    scores = fusionar_rrf([1, 2, 3], [3, 1, 2])
    # El 1 y el 3 aparecen bien rankeados en ambas listas; el 2 solo bien
    # rankeado en una. El 1 y el 3 deberían superar al 2.
    assert scores[1] > scores[2]
    assert scores[3] > scores[2]


def test_fusionar_rrf_con_una_sola_lista_respeta_el_orden() -> None:
    scores = fusionar_rrf([10, 20, 30])
    assert scores[10] > scores[20] > scores[30]


def test_fusionar_rrf_item_ausente_de_una_lista_no_rompe() -> None:
    scores = fusionar_rrf([1, 2], [3])
    assert set(scores) == {1, 2, 3}


def test_fusionar_rrf_listas_vacias() -> None:
    assert fusionar_rrf([], []) == {}
