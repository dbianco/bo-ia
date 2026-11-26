"""Plan 2: vectors computed elsewhere, replayed offline."""
import numpy as np
import pytest

from src.processor.hashed_embeddings import HashedEmbeddingProvider
from src.processor.precomputed_embeddings import (
    MissingPrecomputedEmbedding,
    PrecomputedEmbeddingProvider,
    PrecomputedFileError,
    write_precomputed,
)

TEXTS = ["primer fragmento", "segundo fragmento"]


class _Asymmetric:
    """Like the real model: a query and a passage with the same text differ."""

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, float(len(text))]

    def embed_passage(self, text: str) -> list[float]:
        return [0.0, 1.0, float(len(text))]

    def describe(self) -> dict:
        return {"provider": "asymmetric", "version": 7}


def test_replays_the_vectors_of_the_original_provider(tmp_path) -> None:
    original = HashedEmbeddingProvider()
    path = tmp_path / "vectors.npz"
    write_precomputed(path, original, passages=TEXTS, queries=["consulta"])
    replay = PrecomputedEmbeddingProvider(path)
    assert replay.embed_passage(TEXTS[1]) == original.embed_passage(TEXTS[1])
    assert replay.embed_query("consulta") == original.embed_query("consulta")
    assert np.array_equal(replay.embed_passages(TEXTS), original.embed_passages(TEXTS))


def test_queries_and_passages_are_kept_apart(tmp_path) -> None:
    path = tmp_path / "vectors.npz"
    write_precomputed(path, _Asymmetric(), passages=["igual"], queries=["igual"])
    replay = PrecomputedEmbeddingProvider(path, dim=3)
    assert replay.embed_query("igual") == [1.0, 0.0, 5.0]
    assert replay.embed_passage("igual") == [0.0, 1.0, 5.0]


def test_a_missing_text_is_a_clear_error(tmp_path) -> None:
    path = tmp_path / "vectors.npz"
    write_precomputed(path, HashedEmbeddingProvider(), passages=TEXTS, queries=[])
    replay = PrecomputedEmbeddingProvider(path)
    with pytest.raises(MissingPrecomputedEmbedding) as error:
        replay.embed_query("una consulta que nadie calculó")
    message = str(error.value)
    assert "query" in message and "una consulta que nadie" in message and str(path) in message


def test_repeated_texts_are_embedded_once(tmp_path) -> None:
    path = tmp_path / "vectors.npz"
    assert write_precomputed(path, HashedEmbeddingProvider(), passages=TEXTS + TEXTS, queries=[]) == 2


def test_the_same_input_writes_the_same_bytes(tmp_path) -> None:
    for name in ("a.npz", "b.npz"):
        write_precomputed(tmp_path / name, HashedEmbeddingProvider(), passages=TEXTS, queries=["q"])
    assert (tmp_path / "a.npz").read_bytes() == (tmp_path / "b.npz").read_bytes()


def test_description_names_the_original_provider(tmp_path) -> None:
    path = tmp_path / "vectors.npz"
    write_precomputed(path, _Asymmetric(), passages=["x"], queries=[])
    described = PrecomputedEmbeddingProvider(path, dim=3).describe()
    assert described["provider"] == "precomputed"
    assert described["source"] == {"provider": "asymmetric", "version": 7}


@pytest.mark.parametrize("content", [None, b"", b"not a zip file"])
def test_an_unreadable_file_is_a_clear_error(tmp_path, content) -> None:
    path = tmp_path / "vectors.npz"
    if content is not None:
        path.write_bytes(content)
    with pytest.raises(PrecomputedFileError, match="vectors.npz"):
        PrecomputedEmbeddingProvider(path)


def test_a_file_with_other_arrays_is_a_clear_error(tmp_path) -> None:
    path = tmp_path / "vectors.npz"
    np.savez(path, something=np.zeros(3))
    with pytest.raises(PrecomputedFileError, match="vectors.npz"):
        PrecomputedEmbeddingProvider(path)


def test_a_dimension_that_does_not_fit_the_schema_is_rejected(tmp_path) -> None:
    path = tmp_path / "vectors.npz"
    write_precomputed(path, HashedEmbeddingProvider(dim=64), passages=TEXTS, queries=[])
    with pytest.raises(PrecomputedFileError, match="64.*1024"):
        PrecomputedEmbeddingProvider(path)


def test_nothing_to_embed_is_rejected(tmp_path) -> None:
    with pytest.raises(ValueError):
        write_precomputed(tmp_path / "v.npz", HashedEmbeddingProvider(), passages=[], queries=[])
