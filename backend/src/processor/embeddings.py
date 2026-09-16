"""Proveedor de embeddings: envuelve Qwen/Qwen3-Embedding-0.6B self-hosted
vía sentence-transformers (sección 6 del design spec), más un fake
determinístico para no depender de descargar el modelo real en tests
rápidos.
"""
from __future__ import annotations

import hashlib
import os
from typing import Protocol

MODEL_NAME_DEFAULT = "Qwen/Qwen3-Embedding-0.6B"
EMBEDDING_DIM = 1024

# Qwen3-Embedding recomienda anteponer una instrucción del lado de la
# consulta (no del lado del pasaje) para búsquedas asimétricas.
_QUERY_INSTRUCTION = (
    "Instruct: Given a search query about official government bulletins, "
    "retrieve relevant passages that answer the query\nQuery: {texto}"
)


class EmbeddingProvider(Protocol):
    def embed_query(self, texto: str) -> list[float]: ...
    def embed_passage(self, texto: str) -> list[float]: ...


class SentenceTransformerEmbeddingProvider:
    """Implementación real, self-hosted."""

    def __init__(self, model_name: str | None = None, cache_dir: str | None = None) -> None:
        # Import perezoso: los tests que no la usan no pagan el costo de
        # importar torch/sentence-transformers.
        from sentence_transformers import SentenceTransformer

        self._model_name = model_name or os.environ.get("EMBEDDING_MODEL", MODEL_NAME_DEFAULT)
        cache_folder = cache_dir or os.environ.get("EMBEDDING_CACHE_DIR")
        self._model = SentenceTransformer(self._model_name, cache_folder=cache_folder)

    def embed_query(self, texto: str) -> list[float]:
        prompt = _QUERY_INSTRUCTION.format(texto=texto)
        return self._model.encode(prompt, normalize_embeddings=True).tolist()

    def embed_passage(self, texto: str) -> list[float]:
        return self._model.encode(texto, normalize_embeddings=True).tolist()


class FakeEmbeddingProvider:
    """Embeddings determinísticos y rápidos para tests: NO usa el modelo
    real. Mismo texto -> mismo vector; nunca se usa en producción."""

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self._dim = dim

    def _vector_for(self, texto: str) -> list[float]:
        digest = hashlib.sha256(texto.encode("utf-8")).digest()
        repeticiones = (self._dim // len(digest)) + 1
        crudo = (digest * repeticiones)[: self._dim]
        return [(b / 255.0) * 2 - 1 for b in crudo]

    def embed_query(self, texto: str) -> list[float]:
        return self._vector_for(texto)

    def embed_passage(self, texto: str) -> list[float]:
        return self._vector_for(texto)
