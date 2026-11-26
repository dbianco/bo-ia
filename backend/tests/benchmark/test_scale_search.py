"""Plan 4: the scale benchmark of the search engine, at a small size."""
import json

import pytest

from src.benchmark.__main__ import main
from src.benchmark.scale_search import ScaleSearchConfig, run_scale_search

pytestmark = pytest.mark.usefixtures("no_network")


@pytest.fixture(scope="module")
def result():
    return run_scale_search(
        ScaleSearchConfig(seed=5, documents=5000, queries=40, dim=256, graph_from=0, widths="32,64,128")
    )


def test_pruned_lexical_results_equal_the_exhaustive_ones(result) -> None:
    assert result.report["lexical"]["different_top_10"] == 0
    assert result.report["lexical"]["queries"] == 40


def test_recall_with_and_without_filters(result) -> None:
    curve = {(row["allowed"], row["width"]): row["recall@10"] for row in result.report["vector_curve"]}
    assert {width for _, width in curve} == {32, 64, 128}
    assert {allowed for allowed, _ in curve} == {1.0, 0.3, 0.1, 0.01}
    assert curve[(0.01, 64)] >= 0.95 and curve[(1.0, 128)] >= 0.95
    assert curve[(1.0, 128)] >= curve[(1.0, 32)]


def test_quality_of_the_modes(result) -> None:
    quality = result.report["quality"]
    assert set(quality) == {"lexical", "semantic", "hybrid", "all"}
    best = max(quality["lexical"]["paraphrase"]["ndcg@10"], quality["semantic"]["paraphrase"]["ndcg@10"])
    assert quality["hybrid"]["paraphrase"]["ndcg@10"] >= best


def test_latencies_are_apart(result) -> None:
    assert {"lexical", "semantic", "hybrid", "all", "vector_curve", "build_seconds"} <= set(result.timings)
    assert result.timings["hybrid"]["p95_ms"] > 0
    assert "_ms" not in json.dumps(result.report)


def test_command(tmp_path, capsys) -> None:
    main(["scale-search", "--documents", "400", "--queries", "10", "--dim", "128", "--widths", "16,32,64", "--out", str(tmp_path)])
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["fragments"] > 400
    assert "recall@10" in capsys.readouterr().out


def test_engine_modes_are_systems_of_the_main_benchmark(tmp_path) -> None:
    names = ["engine-lexical", "engine-semantic", "engine-hybrid", "engine-all"]
    main(["run", "--documents", "300", "--systems", ",".join(["vector-exact", *names]), "--out", str(tmp_path)])
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert set(report["search"]) == {"vector-exact", *names}
