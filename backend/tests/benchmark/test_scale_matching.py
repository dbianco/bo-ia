"""Plan 3: the scale benchmark of the matching engine, at a small size."""
import json

import pytest

from src.benchmark.__main__ import main
from src.benchmark.scale_matching import ScaleMatchingConfig, run_scale_matching

pytestmark = pytest.mark.usefixtures("no_network")


@pytest.fixture(scope="module")
def result():
    return run_scale_matching(
        ScaleMatchingConfig(
            seed=5, subscriptions=6000, corpus_documents=800, documents=10, fragments=20, dim=256, graph_from=0,
            exact_below=0, reference_documents=2,
        )
    )  # fmt: skip


def test_the_engine_meets_the_criteria_against_brute_force(result) -> None:
    quality = result.report["quality"]
    assert quality["matches"] > 200
    assert quality["recall"] >= 0.99
    assert quality["precision"] == 1.0
    assert quality["largest_score_error"] <= 1e-5


def test_the_exact_scan_used_as_truth_agrees_with_the_loop(result) -> None:
    """Recall is measured against a scan, because the loop over every
    subscription is too slow to run on all the documents."""
    assert result.report["reference"]["documents"] == 2
    assert result.report["reference"]["differences"] == 0


def test_timings_and_machine_are_apart(result) -> None:
    assert {"loop", "scan", "indexed", "build_seconds"} <= set(result.timings)
    assert result.timings["machine"]["cpu_count"]
    assert "seconds" not in json.dumps(result.report)
    assert result.timings["speedup_over_loop"] > 1


def test_command(tmp_path, capsys) -> None:
    main(["scale-matching", "--subscriptions", "800", "--corpus-documents", "300", "--documents", "4", "--fragments", "3",
          "--dim", "128", "--out", str(tmp_path)])
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["config"]["subscriptions"] == 800
    assert report["embedding"]["provider"] == "hashed"
    assert report["quality"]["recall"] == 1.0, "few subscriptions are scanned"
    assert (tmp_path / "timings.json").exists()
    assert "recall" in capsys.readouterr().out


def test_indexed_matching_is_a_system_of_the_main_benchmark(tmp_path) -> None:
    main(["run", "--documents", "300", "--systems", "match-brute-force,match-indexed", "--out", str(tmp_path)])
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["matching"]["match-indexed"] == report["matching"]["match-brute-force"]
