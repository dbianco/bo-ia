"""T014: generación de embeddings y el filtro de umbral de similitud
(FR-015)."""
from dataclasses import dataclass

import pytest

from src.processor.embeddings import FakeEmbeddingProvider
from src.processor.threshold import filtrar_por_umbral, umbral_configurado


@dataclass
class ResultadoFalso:
    fragmento_id: int
    similitud: float


def test_fake_embedding_provider_es_deterministico() -> None:
    provider = FakeEmbeddingProvider(dim=8)
    a1 = provider.embed_passage("hola mundo")
    a2 = provider.embed_passage("hola mundo")
    b = provider.embed_passage("otro texto")

    assert a1 == a2
    assert a1 != b
    assert len(a1) == 8


def test_fake_embedding_provider_embed_query() -> None:
    provider = FakeEmbeddingProvider(dim=8)
    assert len(provider.embed_query("una consulta")) == 8


def test_filtrar_por_umbral_descarta_resultados_por_debajo() -> None:
    resultados = [
        ResultadoFalso(fragmento_id=1, similitud=0.9),
        ResultadoFalso(fragmento_id=2, similitud=0.4),
        ResultadoFalso(fragmento_id=3, similitud=0.6),
    ]
    filtrados = filtrar_por_umbral(resultados, umbral=0.5)
    assert [r.fragmento_id for r in filtrados] == [1, 3]


def test_filtrar_por_umbral_conserva_el_orden() -> None:
    resultados = [ResultadoFalso(fragmento_id=i, similitud=0.9 - i * 0.01) for i in range(5)]
    filtrados = filtrar_por_umbral(resultados, umbral=0.0)
    assert [r.fragmento_id for r in filtrados] == [0, 1, 2, 3, 4]


def test_filtrar_por_umbral_puede_devolver_lista_vacia() -> None:
    resultados = [ResultadoFalso(fragmento_id=1, similitud=0.1)]
    assert filtrar_por_umbral(resultados, umbral=0.5) == []


def test_umbral_configurado_lee_variable_de_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMILARITY_THRESHOLD", "0.73")
    assert umbral_configurado() == pytest.approx(0.73)


@pytest.mark.slow
def test_embedding_real_qwen3_0_6b_genera_vector_de_1024_dimensiones() -> None:
    """Verificación de integración real contra el modelo self-hosted
    (sección 6 del design spec). Se salta en corridas rápidas con
    `-m "not slow"` porque descarga el modelo real (~1 GB)."""
    from src.processor.embeddings import SentenceTransformerEmbeddingProvider

    provider = SentenceTransformerEmbeddingProvider()
    vector = provider.embed_passage("Decreto 123/2026 sobre presupuesto provincial.")
    assert len(vector) == 1024
