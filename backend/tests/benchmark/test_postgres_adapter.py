"""The adapter for the current PostgreSQL search (existing-suite test: needs the database)."""
import os

import psycopg
import pytest

from src.benchmark.harness import evaluate_matching, evaluate_search
from src.benchmark.postgres import PostgresMatch, PostgresSearch, scratch_database
from src.processor.embeddings import FakeEmbeddingProvider
from src.synthetic.corpus import CorpusConfig, generate_corpus
from tests.conftest import ADMIN_DATABASE_URL


@pytest.fixture(scope="module")
def corpus():
    return generate_corpus(CorpusConfig(seed=4, documents=100, queries=30, subscriptions=5))


def _databases() -> set[str]:
    dsn = ADMIN_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn.rsplit("/", 1)[0] + "/postgres", autocommit=True) as conn:
        return {row[0] for row in conn.execute("SELECT datname FROM pg_database")}


def test_scratch_database_is_created_apart_and_dropped() -> None:
    before = _databases()
    environment = os.environ.get("DATABASE_URL")
    with scratch_database(ADMIN_DATABASE_URL) as url:
        assert url != ADMIN_DATABASE_URL
        assert len(_databases() - before) == 1
    assert _databases() == before
    assert os.environ.get("DATABASE_URL") == environment


def test_search_and_match_run_against_the_real_implementation(corpus) -> None:
    provider = FakeEmbeddingProvider()
    with scratch_database(ADMIN_DATABASE_URL) as url:
        # Every text gets an arbitrary vector, so only the lexical half of "hybrid" can find anything.
        with PostgresMatch(url, corpus, provider, threshold=0.99) as match:
            quality, _ = evaluate_matching(match, corpus)
            assert quality["true_positives"] == 0
            with PostgresSearch(url, corpus, provider, mode="hybrid", threshold=0.99) as search:
                assert search.name == "postgres-hybrid"
                quality, timing = evaluate_search(search, corpus, ks=(10,))
                assert 0 < quality["all"]["mrr"] <= 1
                assert timing["p50_ms"] > 0


def test_threshold_does_not_leak_to_the_environment(corpus, monkeypatch) -> None:
    monkeypatch.setenv("SIMILARITY_THRESHOLD", "0.73")
    with scratch_database(ADMIN_DATABASE_URL) as url:
        with PostgresSearch(url, corpus, FakeEmbeddingProvider(), mode="semantic", threshold=0.1):
            pass
    assert os.environ["SIMILARITY_THRESHOLD"] == "0.73"


def test_scale_command_measures_postgres_on_a_bulk_loaded_database(tmp_path, capsys) -> None:
    import json

    from src.benchmark.__main__ import main

    before = _databases()
    main(["scale-search", "--documents", "300", "--queries", "5", "--database-url", ADMIN_DATABASE_URL,
          "--out", str(tmp_path)])  # fmt: skip
    timings = json.loads((tmp_path / "timings.json").read_text(encoding="utf-8"))
    assert {"semantic", "hybrid", "all", "read_10_rows", "load_seconds"} <= set(timings)
    assert "hybrid" in capsys.readouterr().out
    assert _databases() == before


def test_scale_matching_measures_the_sql_loop(tmp_path) -> None:
    import json

    from src.benchmark.__main__ import main

    main(["scale-matching", "--subscriptions", "50", "--corpus-documents", "200", "--documents", "3", "--fragments", "2",
          "--database-url", ADMIN_DATABASE_URL, "--out", str(tmp_path)])  # fmt: skip
    timings = json.loads((tmp_path / "timings.json").read_text(encoding="utf-8"))
    assert timings["sql_loop"]["measured_subscriptions"] == 50
    assert timings["sql_loop"]["ms_per_subscription"] > 0
