"""Plan 1: deterministic corpus with planted relevance."""
import hashlib
import json
import re
import time
from pathlib import Path

import pytest

from src.config.installation import cargar_installation_config
from src.ingestor.contract import DocumentoNormalizado
from src.synthetic.corpus import PROFILES, CorpusConfig, generate_corpus, satisfies_filters, write_corpus
from src.text.tokens import content_tokens

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
SMALL = CorpusConfig(seed=11, documents=1200)


@pytest.fixture(scope="module", params=["gazette", "tenders"])
def corpus(request):
    return generate_corpus(CorpusConfig(seed=11, documents=1200, profile=request.param))


@pytest.fixture(scope="module")
def gazette():
    return generate_corpus(SMALL)


def _digest(directory: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.iterdir())}


@pytest.mark.parametrize("profile", ["gazette", "tenders"])
def test_same_seed_writes_identical_files(tmp_path: Path, profile: str) -> None:
    config = CorpusConfig(seed=5, documents=300, profile=profile)
    write_corpus(generate_corpus(config), tmp_path / "a")
    write_corpus(generate_corpus(config), tmp_path / "b")
    assert _digest(tmp_path / "a") == _digest(tmp_path / "b")
    assert set(_digest(tmp_path / "a")) == {"documents.jsonl", "truth.json", "synonyms.json"}


def test_output_does_not_depend_on_the_process_hash_seed(tmp_path: Path) -> None:
    """Set and dict ordering vary with PYTHONHASHSEED; the corpus must not."""
    import os
    import subprocess
    import sys

    for seed in ("0", "1"):
        subprocess.run(
            [sys.executable, "-m", "src.benchmark", "generate", "--documents", "200", "--seed", "5",
             "--out", str(tmp_path / seed)],
            check=True, capture_output=True, env={**os.environ, "PYTHONHASHSEED": seed},
            cwd=Path(__file__).resolve().parents[2],
        )
    assert _digest(tmp_path / "0") == _digest(tmp_path / "1")


def test_another_seed_gives_another_corpus(gazette) -> None:
    other = generate_corpus(CorpusConfig(seed=12, documents=1200))
    assert [d.texto for d in other.documents] != [d.texto for d in gazette.documents]


def test_documents_follow_the_ingestion_contract(corpus) -> None:
    assert len(corpus.documents) == 1200
    assert all(isinstance(d, DocumentoNormalizado) for d in corpus.documents)
    ids = [d.identificador_externo for d in corpus.documents]
    assert len(set(ids)) == len(ids)
    texts = [d.texto for d in corpus.documents]
    assert len(set(texts)) == len(texts), "identical texts would be dropped as duplicates on ingestion"


@pytest.mark.parametrize(
    ("profile", "installation"),
    [("gazette", "installation.yaml"), ("tenders", "installation-licitaciones.yaml")],
)
def test_metadata_uses_the_filters_the_installation_declares(profile: str, installation: str) -> None:
    declared = cargar_installation_config(CONFIG_DIR / installation).filtros
    assert {f.clave: f.tipo for f in declared} == {f.clave: f.tipo for f in PROFILES[profile].filters}
    documents = generate_corpus(CorpusConfig(seed=1, documents=200, profile=profile)).documents
    assert {k for d in documents for k in d.metadata} == {f.clave for f in declared}


def test_every_query_and_subscription_has_an_answer(corpus) -> None:
    ids = {d.identificador_externo for d in corpus.documents}
    assert corpus.truth.queries and corpus.truth.subscriptions
    for query in corpus.truth.queries:
        assert 2 in query.relevant.values(), query.id
        assert set(query.relevant) <= ids
        assert set(query.relevant.values()) <= {1, 2}
    for subscription in corpus.truth.subscriptions:
        assert subscription.must_match and set(subscription.must_match) <= ids


def test_truth_respects_the_query_filters(corpus) -> None:
    by_id = {d.identificador_externo: d for d in corpus.documents}
    filtered = [q for q in corpus.truth.queries if q.filters]
    assert filtered, "some queries must carry filters"
    for q in filtered:
        assert all(satisfies_filters(by_id[i].metadata, q.filters) for i in q.relevant)
        topic_ids = set(corpus.truth.topics[q.topic])
        expected = {i for i in topic_ids if satisfies_filters(by_id[i].metadata, q.filters)}
        assert {i for i, g in q.relevant.items() if g == 2} == expected


@pytest.mark.parametrize(
    ("metadata", "filters", "expected"),
    [
        ({"provincia": "Córdoba"}, {"provincia": "Córdoba"}, True),
        ({"provincia": "San Luis"}, {"provincia": "Córdoba"}, False),
        ({}, {"provincia": "Córdoba"}, False),
        ({"monto": 100.0}, {"monto": "100,200"}, True),
        ({"monto": 200.0}, {"monto": "100,200"}, True),
        ({"monto": 201.0}, {"monto": "100,200"}, False),
        ({"monto": 201.0}, {"monto": "100,"}, True),
        ({"monto": 5.0}, {"monto": ",10"}, True),
        ({}, {"monto": "100,"}, False),
    ],
)
def test_truth_filter_semantics(metadata: dict, filters: dict, expected: bool) -> None:
    assert satisfies_filters(metadata, filters) is expected


def test_paraphrase_queries_share_no_concept_word_with_their_exact_documents(gazette) -> None:
    by_id = {d.identificador_externo: d for d in gazette.documents}
    paraphrase = [q for q in gazette.truth.queries if q.kind == "paraphrase"]
    control = [q for q in gazette.truth.queries if q.kind == "same_vocabulary"]
    assert paraphrase and control

    def overlap(q) -> float:
        exact = [i for i, g in q.relevant.items() if g == 2]
        words = set(q.concept_words)
        return sum(len(words & set(content_tokens(by_id[i].texto))) / len(words) for i in exact) / len(exact)

    mean = lambda qs: sum(map(overlap, qs)) / len(qs)  # noqa: E731
    assert mean(paraphrase) < 0.25
    assert mean(control) > 0.4


def test_republications_change_only_date_and_number(gazette) -> None:
    by_id = {d.identificador_externo: d for d in gazette.documents}
    assert gazette.truth.republications
    share = sum(len(g) - 1 for g in gazette.truth.republications) / len(gazette.documents)
    assert 0.05 < share < 0.4
    for group in gazette.truth.republications:
        copies = [by_id[i] for i in group]
        assert len(group) >= 2
        assert len({c.fecha for c in copies}) == len(copies), "each copy is published on another day"
        assert all(c.metadata == copies[0].metadata for c in copies)
        bodies = {re.sub(r"Aviso Nº \d+ - \d{1,2}/\d{1,2}/\d{4}\.$", "", c.texto) for c in copies}
        assert len(bodies) == 1
        assert len({c.texto for c in copies}) == len(copies)


def test_distractors_share_words_with_the_query_but_belong_elsewhere(gazette) -> None:
    by_id = {d.identificador_externo: d for d in gazette.documents}
    queries = {q.id: q for q in gazette.truth.queries}
    topic_of = {i: t for t, ids in gazette.truth.topics.items() for i in ids}
    assert gazette.truth.distractors
    for query_id, ids in gazette.truth.distractors.items():
        query = queries[query_id]
        for i in ids:
            assert i not in query.relevant
            assert topic_of[i] != query.topic
            assert set(query.concept_words) & set(content_tokens(by_id[i].texto))


def test_topics_partition_the_documents(corpus) -> None:
    ids = [i for members in corpus.truth.topics.values() for i in members]
    assert sorted(ids) == sorted(d.identificador_externo for d in corpus.documents)


def test_synonym_table_covers_the_requested_share(gazette) -> None:
    full, half, none = (gazette.synonym_table(c) for c in (1.0, 0.5, 0.0))
    count = lambda t: sum(len(v) for v in t.values())  # noqa: E731
    assert count(none) == 0
    assert 0.35 < count(half) / count(full) < 0.65
    assert half == gazette.synonym_table(0.5)


def test_truth_file_is_plain_json(tmp_path: Path, gazette) -> None:
    write_corpus(gazette, tmp_path)
    truth = json.loads((tmp_path / "truth.json").read_text(encoding="utf-8"))
    assert {"seed", "profile", "queries", "subscriptions", "republications", "topics", "distractors"} <= set(truth)
    assert truth["queries"][0]["relevant"]
    assert len((tmp_path / "documents.jsonl").read_text(encoding="utf-8").splitlines()) == 1200


def test_generation_speed_allows_a_million_fragments_in_minutes() -> None:
    """Guard with a wide margin (the plan records the measured figure)."""
    start = time.perf_counter()
    generate_corpus(CorpusConfig(seed=3, documents=5000))
    assert (time.perf_counter() - start) / 5000 * 1_000_000 < 20 * 60


def test_invalid_config_is_rejected() -> None:
    with pytest.raises(ValueError, match="profile"):
        generate_corpus(CorpusConfig(seed=1, documents=100, profile="nope"))
    with pytest.raises(ValueError, match="documents"):
        generate_corpus(CorpusConfig(seed=1, documents=10))
