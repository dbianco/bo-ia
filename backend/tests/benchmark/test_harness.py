"""Plan 1: the harness runs any implementation and reports stable figures."""
import json
from pathlib import Path

import pytest

from src.benchmark.__main__ import main
from src.benchmark.harness import evaluate_matching, evaluate_search, run_benchmark, write_report
from src.benchmark.systems import BruteForceMatch, LexicalSearch, OracleMatch, OracleSearch
from src.synthetic.corpus import CorpusConfig, generate_corpus

pytestmark = pytest.mark.usefixtures("no_network")


@pytest.fixture(scope="module")
def corpus():
    return generate_corpus(CorpusConfig(seed=21, documents=1500))


def test_oracle_is_perfect(corpus) -> None:
    quality, _ = evaluate_search(OracleSearch(corpus.truth), corpus, ks=(10, 50))
    assert quality["all"]["recall@50"] == 1.0
    assert quality["all"]["mrr"] == 1.0
    assert quality["all"]["ndcg@10"] == 1.0


def test_lexical_baseline_is_clearly_below_the_oracle_on_paraphrase_queries(corpus) -> None:
    lexical, _ = evaluate_search(LexicalSearch(corpus.documents, corpus.profile.filters), corpus, ks=(10, 50))
    oracle, _ = evaluate_search(OracleSearch(corpus.truth), corpus, ks=(10, 50))
    assert lexical["paraphrase"]["recall@50"] < 0.5 * oracle["paraphrase"]["recall@50"]
    assert lexical["paraphrase"]["ndcg@10"] < 0.5 * oracle["paraphrase"]["ndcg@10"]


def test_lexical_baseline_is_not_broken(corpus) -> None:
    """The gap above must come from the paraphrases, not from a bad baseline."""
    lexical, _ = evaluate_search(LexicalSearch(corpus.documents, corpus.profile.filters), corpus, ks=(10, 50))
    assert lexical["same_vocabulary"]["mrr"] > 0.8
    assert lexical["same_vocabulary"]["recall@50"] > 2 * lexical["paraphrase"]["recall@50"]


def test_lexical_search_applies_filters(corpus) -> None:
    by_id = {d.identificador_externo: d for d in corpus.documents}
    system = LexicalSearch(corpus.documents, corpus.profile.filters)
    hits = system.search(corpus.truth.queries[0].text, {"provincia": "Córdoba"}, 20)
    assert hits and all(by_id[i].metadata["provincia"] == "Córdoba" for i in hits)


def test_lexical_ranking_matches_a_direct_bm25_computation() -> None:
    import datetime
    import math

    from src.ingestor.contract import DocumentoNormalizado

    texts = {"a": "puente puente rio", "b": "puente camino largo norte", "c": "escuela"}
    documents = [
        DocumentoNormalizado("f", i, datetime.date(2026, 1, 1), t, "https://example.org") for i, t in texts.items()
    ]
    system = LexicalSearch(documents, [])

    def bm25(tf: int, length: int) -> float:
        k1, b, n, df, average = 1.2, 0.75, 3, 2, (3 + 4 + 1) / 3
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        return idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / average))

    scores = dict(system.scored("puente", {}, 10))
    assert scores == {"a": pytest.approx(bm25(2, 3)), "b": pytest.approx(bm25(1, 4))}
    assert system.search("puente", {}, 10) == ["a", "b"]


def test_oracle_matching_is_perfect_and_empty_matching_is_not(corpus) -> None:
    quality, _ = evaluate_matching(OracleMatch(corpus.truth), corpus)
    assert quality["precision"] == quality["recall"] == 1.0

    class Silent:
        name = "silent"

        def match(self, document) -> set[str]:
            return set()

    quality, _ = evaluate_matching(Silent(), corpus)
    assert quality["recall"] == 0.0


def test_brute_force_matching_applies_threshold_and_filters() -> None:
    import datetime

    from src.ingestor.contract import DocumentoNormalizado
    from src.synthetic.corpus import Subscription

    class Fixed:
        vectors = {"near": [1.0, 0.0], "far": [0.0, 1.0]}

        def embed_query(self, text):
            return self.vectors[text]

        embed_passage = embed_query

    subs = [
        Subscription("s1", "near", {}, []),
        Subscription("s2", "far", {}, []),
        Subscription("s3", "near", {"provincia": "San Luis"}, []),
    ]
    from src.config.installation import FiltroSeleccion

    filters = [FiltroSeleccion(clave="provincia", etiqueta="Provincia")]
    system = BruteForceMatch(subs, Fixed(), filters, threshold=0.5)
    document = DocumentoNormalizado(
        "f", "d", datetime.date(2026, 1, 1), "near", "https://example.org", metadata={"provincia": "Córdoba"}
    )
    assert system.match(document) == {"s1"}


def test_report_files_are_stable_and_timings_are_separate(tmp_path: Path, corpus) -> None:
    for name in ("a", "b"):
        systems = [OracleSearch(corpus.truth), LexicalSearch(corpus.documents, corpus.profile.filters)]
        result = run_benchmark(corpus, search_systems=systems, match_systems=[OracleMatch(corpus.truth)])
        write_report(result, tmp_path / name)

    for file in ("report.json", "report.txt"):
        assert (tmp_path / "a" / file).read_bytes() == (tmp_path / "b" / file).read_bytes()

    report = json.loads((tmp_path / "a" / "report.json").read_text(encoding="utf-8"))
    assert report["corpus"]["seed"] == 21
    assert report["corpus"]["documents"] == 1500
    assert set(report["search"]) == {"oracle", "lexical-bm25"}
    assert not any("latency" in key for key in json.dumps(report).split('"'))

    timings = json.loads((tmp_path / "a" / "timings.json").read_text(encoding="utf-8"))
    assert timings["machine"]["cpu_count"]
    assert {"p50_ms", "p95_ms", "p99_ms", "per_second"} <= set(timings["search"]["lexical-bm25"])
    assert "lexical-bm25" in (tmp_path / "a" / "report.txt").read_text(encoding="utf-8")


def test_a_system_that_returns_unknown_documents_is_reported(corpus) -> None:
    class Broken:
        name = "broken"

        def search(self, query, filters, k):
            return ["does-not-exist"]

    with pytest.raises(ValueError, match="does-not-exist"):
        evaluate_search(Broken(), corpus, ks=(10,))


def test_command_line_generate_and_run(tmp_path: Path, capsys) -> None:
    main(["generate", "--profile", "tenders", "--seed", "3", "--documents", "300", "--out", str(tmp_path / "corpus")])
    assert (tmp_path / "corpus" / "truth.json").exists()

    main(["run", "--profile", "tenders", "--seed", "3", "--documents", "300", "--systems", "oracle,lexical",
          "--out", str(tmp_path / "run")])
    assert (tmp_path / "run" / "report.json").exists()
    assert "oracle" in capsys.readouterr().out


def test_command_line_rejects_unknown_systems(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["run", "--documents", "300", "--systems", "oracle,magic", "--out", str(tmp_path)])


def test_postgres_systems_need_an_explicit_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The benchmark must never fall back to the installation's own database."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@localhost:1/production")
    with pytest.raises(SystemExit):
        main(["run", "--documents", "300", "--systems", "postgres-semantic", "--out", str(tmp_path)])
