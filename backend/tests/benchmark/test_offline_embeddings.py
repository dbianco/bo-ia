"""Plan 2 on the corpus of plan 1, with the network off."""
import builtins
import json

import pytest

from src.benchmark.__main__ import main
from src.benchmark.harness import evaluate_matching, evaluate_search
from src.benchmark.systems import BruteForceMatch, LexicalSearch, VectorExactSearch
from src.processor.hashed_embeddings import HashedEmbeddingProvider
from src.synthetic.corpus import CorpusConfig, generate_corpus

pytestmark = pytest.mark.usefixtures("no_network", "no_model")
COVERAGE = 0.8  # the default of the command; see docs/plans/02


@pytest.fixture()
def no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "transformers", "sentence_transformers"}:
            raise AssertionError(f"{name} imported: a model would be loaded")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)


@pytest.fixture(scope="module")
def corpus():
    return generate_corpus(CorpusConfig(seed=33, documents=1500))


@pytest.fixture(scope="module")
def provider(corpus):
    return HashedEmbeddingProvider(synonyms=corpus.synonym_table(COVERAGE))


@pytest.fixture(scope="module")
def vector(corpus, provider):
    return VectorExactSearch(corpus.documents, provider, corpus.profile.filters)


def test_nearest_neighbours_are_mostly_from_the_same_topic(corpus, vector) -> None:
    topic_of = {i: t for t, ids in corpus.truth.topics.items() for i in ids}
    copies = {i: set(g) for g in corpus.truth.republications for i in g}
    ids = [d.identificador_externo for d in corpus.documents]
    k, precisions = 5, []
    positions = list(range(0, len(ids), 7))
    # Republished copies are near-identical; counting them would make this easy.
    for position, found in zip(positions, vector.neighbours(positions, k + 5), strict=True):
        own = ids[position]
        others = [ids[j] for j in found if ids[j] not in copies.get(own, set())][:k]
        precisions.append(sum(topic_of[o] == topic_of[own] for o in others) / k)
    assert sum(precisions) / len(precisions) > 0.5


def test_semantic_search_beats_lexical_on_paraphrases_without_being_an_oracle(corpus, vector) -> None:
    semantic, _ = evaluate_search(vector, corpus)
    lexical, _ = evaluate_search(LexicalSearch(corpus.documents, corpus.profile.filters), corpus)
    assert semantic["paraphrase"]["recall@50"] > 1.5 * lexical["paraphrase"]["recall@50"]
    # A perfect score would mean the synonym table hands over the answer.
    assert semantic["paraphrase"]["recall@50"] < 0.98


def test_without_synonyms_there_is_no_semantic_advantage(corpus) -> None:
    plain = VectorExactSearch(corpus.documents, HashedEmbeddingProvider(), corpus.profile.filters)
    quality, _ = evaluate_search(plain, corpus)
    lexical, _ = evaluate_search(LexicalSearch(corpus.documents, corpus.profile.filters), corpus)
    assert quality["paraphrase"]["recall@50"] < 1.5 * lexical["paraphrase"]["recall@50"]


def test_matching_depends_on_meaning(corpus, provider) -> None:
    system = BruteForceMatch(corpus.truth.subscriptions, provider, corpus.profile.filters, threshold=0.45)
    quality, _ = evaluate_matching(system, corpus)
    assert quality["recall"] > 0.4 and quality["precision"] > 0.3


def test_vector_search_applies_filters_exactly(corpus, vector) -> None:
    by_id = {d.identificador_externo: d for d in corpus.documents}
    query = corpus.truth.queries[0].text
    everything = vector.search(query, {}, len(by_id))
    filtered = vector.search(query, {"municipio": "Cosquín"}, len(by_id))
    assert filtered == [i for i in everything if by_id[i].metadata.get("municipio") == "Cosquín"]


def test_benchmark_command_runs_offline_and_names_the_provider(tmp_path) -> None:
    arguments = ["run", "--documents", "300", "--provider", "hashed", "--systems",
                 "oracle,lexical,vector-exact,match-brute-force"]
    main([*arguments, "--out", str(tmp_path / "a")])
    main([*arguments, "--out", str(tmp_path / "b")])
    assert (tmp_path / "a/report.json").read_bytes() == (tmp_path / "b/report.json").read_bytes()
    report = json.loads((tmp_path / "a/report.json").read_text(encoding="utf-8"))
    assert report["embedding"]["provider"] == "hashed"
    assert report["embedding"]["synonym_coverage"] == COVERAGE
    assert report["match_threshold"] is not None
    assert set(report["search"]) == {"oracle", "lexical-bm25", "vector-exact"}
    assert "provider=hashed" in (tmp_path / "a/report.txt").read_text(encoding="utf-8")


def test_precomputed_vectors_replay_the_same_report(tmp_path) -> None:
    common = ["--documents", "200", "--seed", "8"]
    main(["precompute", *common, "--provider", "hashed", "--out", str(tmp_path / "vectors.npz")])
    run = ["run", *common, "--systems", "vector-exact,match-brute-force"]
    main([*run, "--provider", "hashed", "--out", str(tmp_path / "live")])
    main([*run, "--provider", "precomputed", "--precomputed", str(tmp_path / "vectors.npz"),
          "--out", str(tmp_path / "replay")])
    live, replay = (json.loads((tmp_path / n / "report.json").read_text(encoding="utf-8")) for n in ("live", "replay"))
    assert live["search"] == replay["search"] and live["matching"] == replay["matching"]
    assert replay["embedding"]["source"]["provider"] == "hashed"


def test_replaying_another_corpus_fails_clearly(tmp_path, capsys) -> None:
    main(["precompute", "--documents", "200", "--seed", "8", "--out", str(tmp_path / "vectors.npz")])
    with pytest.raises(SystemExit):
        main(["run", "--documents", "200", "--seed", "9", "--systems", "vector-exact", "--provider", "precomputed",
              "--precomputed", str(tmp_path / "vectors.npz"), "--out", str(tmp_path / "run")])
    assert "No precomputed" in capsys.readouterr().err
