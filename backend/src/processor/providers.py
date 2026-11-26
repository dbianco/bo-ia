"""Chooses the embedding provider from settings.

- `model` (default): the real model, for production.
- `hashed`: offline and deterministic, for tests, benchmarks and development.
- `precomputed`: vectors from a file.

The vectors of two providers are not comparable. A database filled with one
must not be searched with another."""
from __future__ import annotations

import json
import os
from pathlib import Path

from src.processor.embeddings import EmbeddingProvider, SentenceTransformerEmbeddingProvider
from src.processor.hashed_embeddings import HashedEmbeddingProvider
from src.processor.precomputed_embeddings import PrecomputedEmbeddingProvider

PROVIDERS = ("model", "hashed", "precomputed")


class EmbeddingConfigError(ValueError):
    """The embedding settings are not valid."""


def load_synonyms(path: Path | str) -> dict[str, list[str]]:
    """A JSON object: concept -> phrases that mean the same."""
    try:
        table = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EmbeddingConfigError(f"cannot read the synonym table {path}: {exc}") from exc
    valid = isinstance(table, dict) and all(
        isinstance(phrases, list) and all(isinstance(p, str) for p in phrases) for phrases in table.values()
    )
    if not valid:
        raise EmbeddingConfigError(f"the synonym table {path} must map each concept to a list of phrases")
    return table


def create_provider(
    name: str,
    *,
    seed: int = 0,
    synonyms_file: Path | str | None = None,
    precomputed_file: Path | str | None = None,
) -> EmbeddingProvider:
    if name == "model":
        return SentenceTransformerEmbeddingProvider()
    if name == "hashed":
        try:
            return HashedEmbeddingProvider(seed=seed, synonyms=load_synonyms(synonyms_file) if synonyms_file else None)
        except EmbeddingConfigError:
            raise
        except ValueError as exc:
            raise EmbeddingConfigError(f"the synonym table {synonyms_file} is not valid: {exc}") from exc
    if name == "precomputed":
        if not precomputed_file:
            raise EmbeddingConfigError("the precomputed provider needs a vector file (EMBEDDING_PRECOMPUTED)")
        return PrecomputedEmbeddingProvider(precomputed_file)
    raise EmbeddingConfigError(f"unknown embedding provider {name!r}; choose one of {', '.join(PROVIDERS)}")


def provider_from_environment() -> EmbeddingProvider:
    seed = os.environ.get("EMBEDDING_SEED") or "0"
    try:
        seed_number = int(seed)
    except ValueError as exc:
        raise EmbeddingConfigError(f"EMBEDDING_SEED must be a whole number, not {seed!r}") from exc
    return create_provider(
        os.environ.get("EMBEDDING_PROVIDER") or "model",
        seed=seed_number,
        synonyms_file=os.environ.get("EMBEDDING_SYNONYMS"),
        precomputed_file=os.environ.get("EMBEDDING_PRECOMPUTED"),
    )


def describe_provider(provider: EmbeddingProvider) -> dict:
    """The provider and its parameters, for reports and logs."""
    describe = getattr(provider, "describe", None)
    return describe() if describe else {"provider": type(provider).__name__}
