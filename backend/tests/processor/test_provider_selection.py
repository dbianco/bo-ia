"""Plan 2: the provider is chosen by settings."""
import json

import pytest

from src.api import deps
from src.processor import providers
from src.processor.hashed_embeddings import HashedEmbeddingProvider
from src.processor.precomputed_embeddings import PrecomputedEmbeddingProvider, write_precomputed
from src.processor.providers import (
    EmbeddingConfigError,
    create_provider,
    describe_provider,
    provider_from_environment,
)

VARIABLES = ("EMBEDDING_PROVIDER", "EMBEDDING_SEED", "EMBEDDING_SYNONYMS", "EMBEDDING_PRECOMPUTED")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch):
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)
    deps._embedder.cache_clear()
    yield
    deps._embedder.cache_clear()


@pytest.fixture()
def model_stub(monkeypatch: pytest.MonkeyPatch):
    class Stub:
        pass

    monkeypatch.setattr(providers, "SentenceTransformerEmbeddingProvider", Stub)
    return Stub


@pytest.mark.parametrize("value", [None, "", "model"])
def test_the_real_model_stays_the_default(monkeypatch, model_stub, value) -> None:
    if value is not None:
        monkeypatch.setenv("EMBEDDING_PROVIDER", value)
    assert isinstance(provider_from_environment(), model_stub)


def test_hashed_provider_from_environment(monkeypatch, tmp_path) -> None:
    table = tmp_path / "synonyms.json"
    table.write_text(json.dumps({"p": ["pavimentación", "asfalto"]}), encoding="utf-8")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hashed")
    monkeypatch.setenv("EMBEDDING_SEED", "7")
    monkeypatch.setenv("EMBEDDING_SYNONYMS", str(table))
    provider = provider_from_environment()
    assert isinstance(provider, HashedEmbeddingProvider)
    assert provider.describe()["seed"] == 7
    assert provider.describe()["synonym_phrases"] == 2


def test_precomputed_provider_from_environment(monkeypatch, tmp_path) -> None:
    path = tmp_path / "v.npz"
    write_precomputed(path, HashedEmbeddingProvider(), passages=["a"], queries=[])
    monkeypatch.setenv("EMBEDDING_PROVIDER", "precomputed")
    monkeypatch.setenv("EMBEDDING_PRECOMPUTED", str(path))
    assert isinstance(provider_from_environment(), PrecomputedEmbeddingProvider)


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"EMBEDDING_PROVIDER": "magic"}, "magic"),
        ({"EMBEDDING_PROVIDER": "fake"}, "fake"),
        ({"EMBEDDING_PROVIDER": "precomputed"}, "EMBEDDING_PRECOMPUTED"),
        ({"EMBEDDING_PROVIDER": "hashed", "EMBEDDING_SEED": "abc"}, "EMBEDDING_SEED"),
        ({"EMBEDDING_PROVIDER": "hashed", "EMBEDDING_SYNONYMS": "/no/such/file.json"}, "/no/such/file.json"),
    ],
)
def test_a_wrong_setting_is_a_clear_error(monkeypatch, settings, message) -> None:
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(EmbeddingConfigError, match=message):
        provider_from_environment()


def test_a_malformed_synonym_table_is_a_clear_error(tmp_path) -> None:
    table = tmp_path / "synonyms.json"
    for content in ("not json", "[1]", '{"a": "text"}', '{"a": [1]}'):
        table.write_text(content, encoding="utf-8")
        with pytest.raises(EmbeddingConfigError, match="synonyms.json"):
            create_provider("hashed", synonyms_file=table)


def test_the_api_uses_the_configured_provider(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hashed")
    assert isinstance(deps.get_embedder(), HashedEmbeddingProvider)


def test_a_provider_without_description_is_named_by_its_class() -> None:
    class Custom:
        pass

    assert describe_provider(Custom()) == {"provider": "Custom"}
