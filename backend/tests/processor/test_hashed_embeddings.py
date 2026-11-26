"""Plan 2: offline embeddings that keep related texts near each other."""
import hashlib
import json
import math
import struct
import time

import numpy as np
import pytest

from src.processor.embeddings import EMBEDDING_DIM
from src.processor.hashed_embeddings import HashedEmbeddingProvider

PAVING = "Licitación pública para la pavimentación de calzada en barrio Alberdi"
PAVING_AGAIN = "LICITACION PUBLICA: pavimentacion de calzada, segundo llamado"
ESTATE = "Declaratoria de herederos del causante Gómez, juzgado de primera instancia"


def cosine(a, b) -> float:
    return float(np.dot(a, b))


def test_vectors_have_the_schema_dimension_and_unit_norm() -> None:
    vector = HashedEmbeddingProvider().embed_passage(PAVING)
    assert isinstance(vector, list) and len(vector) == EMBEDDING_DIM
    assert math.sqrt(sum(v * v for v in vector)) == pytest.approx(1.0, abs=1e-6)


def test_same_text_and_seed_give_the_same_vector() -> None:
    assert HashedEmbeddingProvider(seed=3).embed_passage(PAVING) == HashedEmbeddingProvider(seed=3).embed_passage(PAVING)
    assert HashedEmbeddingProvider(seed=3).embed_passage(PAVING) != HashedEmbeddingProvider(seed=4).embed_passage(PAVING)


def test_vector_is_the_same_on_every_machine() -> None:
    """A recorded vector. If this fails, stored vectors and past benchmark
    reports are no longer comparable: bump ALGORITHM_VERSION on purpose."""
    vector = HashedEmbeddingProvider(dim=64, seed=1, synonyms={"c": ["calzada"]}).embed_passage(PAVING)
    digest = hashlib.sha256(struct.pack("<64f", *vector)).hexdigest()
    assert digest == "8825843f432dce57a7d22d541d31bee31fad1c64220c9be9a98cbe0a11378ca9"


def test_shared_vocabulary_is_close_and_unrelated_text_is_not() -> None:
    provider = HashedEmbeddingProvider()
    a, b, c = (np.array(provider.embed_passage(t)) for t in (PAVING, PAVING_AGAIN, ESTATE))
    assert cosine(a, b) > 0.4
    assert abs(cosine(a, c)) < 0.15


def test_case_and_accents_do_not_matter() -> None:
    provider = HashedEmbeddingProvider()
    assert provider.embed_passage("Pavimentación") == provider.embed_passage("PAVIMENTACION")


def test_a_small_edit_moves_the_vector_a_little() -> None:
    """What the SHA-256 fake cannot do."""
    provider = HashedEmbeddingProvider()
    assert cosine(provider.embed_passage(PAVING), provider.embed_passage(PAVING + " norte")) > 0.8


def test_word_order_counts_through_word_pairs() -> None:
    provider = HashedEmbeddingProvider()
    a, b = provider.embed_passage("deuda del estado provincial"), provider.embed_passage("provincial estado del deuda")
    assert 0.5 < cosine(a, b) < 0.999


def test_synonyms_bring_together_texts_that_share_no_word() -> None:
    synonyms = {"paving": ["pavimentación de calzada", "carpeta asfáltica vial"]}
    a, b = "pavimentación de calzada", "carpeta asfáltica vial"
    plain, informed = HashedEmbeddingProvider(), HashedEmbeddingProvider(synonyms=synonyms)
    assert abs(cosine(plain.embed_query(a), plain.embed_passage(b))) < 0.1
    assert cosine(informed.embed_query(a), informed.embed_passage(b)) > 0.5


def test_synonym_phrases_match_whole_phrases_only() -> None:
    provider = HashedEmbeddingProvider(synonyms={"paving": ["carpeta asfáltica vial"]})
    plain = HashedEmbeddingProvider()
    assert provider.embed_passage("carpeta de cuero") == plain.embed_passage("carpeta de cuero")
    assert provider.embed_passage("carpeta asfáltica vial") != plain.embed_passage("carpeta asfáltica vial")


def test_one_phrase_in_two_concepts_is_rejected() -> None:
    with pytest.raises(ValueError, match="(?i)puente"):
        HashedEmbeddingProvider(synonyms={"a": ["puente"], "b": ["Puente"]})


@pytest.mark.parametrize("text", ["", "   ", "¿? ...", "de la y el"])
def test_text_without_features_is_still_a_valid_unit_vector(text: str) -> None:
    """pgvector's cosine distance to a zero vector is NaN."""
    vector = HashedEmbeddingProvider().embed_passage(text)
    assert math.sqrt(sum(v * v for v in vector)) == pytest.approx(1.0, abs=1e-6)


def test_batch_equals_one_by_one() -> None:
    provider = HashedEmbeddingProvider(dim=128, synonyms={"p": ["pavimentación de calzada"]})
    texts = [PAVING, ESTATE, "", PAVING]
    batch = provider.embed_passages(texts)
    assert batch.dtype == np.float32 and batch.shape == (4, 128)
    assert [row.tolist() for row in batch] == [provider.embed_passage(t) for t in texts]


def test_dimension_is_configurable_for_in_process_indexes() -> None:
    assert len(HashedEmbeddingProvider(dim=256).embed_query("x")) == 256
    with pytest.raises(ValueError, match="dim"):
        HashedEmbeddingProvider(dim=4)


def test_description_identifies_the_provider_and_its_parameters() -> None:
    synonyms = {"p": ["pavimentación"]}
    described = HashedEmbeddingProvider(dim=256, seed=9, synonyms=synonyms).describe()
    assert described["provider"] == "hashed"
    assert (described["dim"], described["seed"], described["synonym_phrases"]) == (256, 9, 1)
    assert described != HashedEmbeddingProvider(dim=256, seed=9, synonyms={"p": ["asfalto"]}).describe()
    json.dumps(described)


def test_cache_limit_does_not_change_results() -> None:
    small, large = HashedEmbeddingProvider(cache_size=8), HashedEmbeddingProvider()
    for text in (PAVING, ESTATE, PAVING_AGAIN, PAVING):
        assert small.embed_passage(text) == large.embed_passage(text)


def test_concurrent_use_gives_the_same_vectors() -> None:
    """The API serves requests from a thread pool and shares one provider."""
    from concurrent.futures import ThreadPoolExecutor

    texts = [f"{PAVING} {ESTATE} variante {i} con texto propio {i * 7}" for i in range(300)]
    expected = [HashedEmbeddingProvider(dim=64).embed_passage(t) for t in texts[:20]]
    shared = HashedEmbeddingProvider(dim=64, cache_size=50)
    with ThreadPoolExecutor(8) as pool:
        found = list(pool.map(shared.embed_passage, texts))
    assert found[:20] == expected
    alone = HashedEmbeddingProvider(dim=64)
    assert found == [alone.embed_passage(t) for t in texts]


def test_speed_allows_a_million_fragments_in_minutes() -> None:
    """Guard with a wide margin (the plan records the measured figure)."""
    provider = HashedEmbeddingProvider()
    texts = [f"{PAVING} {ESTATE} expediente {i} de la calle {i % 97} " * 5 for i in range(2000)]
    start = time.perf_counter()
    provider.embed_passages(texts)
    assert (time.perf_counter() - start) / 2000 * 1_000_000 < 20 * 60
