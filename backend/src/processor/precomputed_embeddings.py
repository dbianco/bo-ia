"""Vectors computed once, elsewhere, and replayed offline.

The file is a NumPy `.npz` archive without pickled objects: `keys` (SHA-256 of
each text), `vectors` (float32, one row per key) and `source` (JSON, the
provider that made them). Queries and passages have different keys, because the
real model embeds the same text differently in each role."""
from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from src.processor.embeddings import EMBEDDING_DIM, EmbeddingProvider

_QUERY, _PASSAGE = "query", "passage"


class PrecomputedFileError(ValueError):
    """The vector file cannot be used."""


class MissingPrecomputedEmbedding(KeyError):
    """The file has no vector for a text."""

    def __str__(self) -> str:
        return str(self.args[0])


def _key(role: str, text: str) -> bytes:
    return hashlib.sha256(f"{role}\0{text}".encode()).hexdigest().encode()


def write_precomputed(
    path: Path | str, provider: EmbeddingProvider, *, passages: Sequence[str], queries: Sequence[str]
) -> int:
    """Embeds every distinct text and writes the file. Returns how many."""
    from src.processor.providers import describe_provider

    keys: list[bytes] = []
    vectors: list[list[float]] = []
    for role, texts, embed in (
        (_PASSAGE, passages, provider.embed_passage),
        (_QUERY, queries, provider.embed_query),
    ):
        for text in dict.fromkeys(texts):
            keys.append(_key(role, text))
            vectors.append(embed(text))
    if not keys:
        raise ValueError("there are no texts to embed")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # An open file, because np.savez adds ".npz" to a path that lacks it.
    with Path(path).open("wb") as out:
        np.savez(
            out,
            keys=np.array(keys, dtype="S64"),
            vectors=np.array(vectors, dtype=np.float32),
            source=np.array(json.dumps(describe_provider(provider), sort_keys=True)),
        )
    return len(keys)


class PrecomputedEmbeddingProvider:
    def __init__(self, path: Path | str, *, dim: int = EMBEDDING_DIM) -> None:
        self._path = Path(path)
        try:
            with np.load(self._path, allow_pickle=False) as data:
                keys, self._vectors = data["keys"], data["vectors"]
                self._source = json.loads(str(data["source"]))
        except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile) as exc:
            raise PrecomputedFileError(f"cannot read the precomputed embeddings in {self._path}: {exc}") from exc
        if self._vectors.ndim != 2 or len(keys) != len(self._vectors):
            raise PrecomputedFileError(f"{self._path}: keys and vectors do not correspond")
        if self._vectors.shape[1] != dim:
            raise PrecomputedFileError(f"{self._path}: the vectors have dimension {self._vectors.shape[1]}, not {dim}")
        self._row = {key: position for position, key in enumerate(keys.tolist())}

    def _vector(self, role: str, text: str) -> np.ndarray:
        key = _key(role, text)
        row = self._row.get(key)
        if row is None:
            excerpt = " ".join(text.split())[:80]
            raise MissingPrecomputedEmbedding(
                f"No precomputed {role} embedding in {self._path} for {excerpt!r} (sha256 {key.decode()[:16]}...). "
                "Generate the file again with every text that will be used."
            )
        return self._vectors[row]

    def embed_query(self, texto: str) -> list[float]:
        return self._vector(_QUERY, texto).tolist()

    def embed_passage(self, texto: str) -> list[float]:
        return self._vector(_PASSAGE, texto).tolist()

    def embed_passages(self, texts: Sequence[str]) -> np.ndarray:
        return np.array([self._vector(_PASSAGE, t) for t in texts], dtype=np.float32)

    def describe(self) -> dict:
        digest = hashlib.sha256(self._path.read_bytes()).hexdigest()
        return {"provider": "precomputed", "vectors": len(self._row), "sha256": digest[:16], "source": self._source}
