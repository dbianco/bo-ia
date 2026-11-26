"""Metric code against values computed by hand (plan 1, success criteria)."""
import math

import pytest

from src.benchmark.metrics import (
    match_scores,
    mean,
    ndcg_at_k,
    percentile,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

RELEVANT = {"a": 2, "b": 2, "c": 1}
RANKING = ["x", "a", "c", "y", "b"]


def test_precision_at_k() -> None:
    # Only grade 2 counts as relevant: a, b.
    assert precision_at_k(RANKING, RELEVANT, 1) == 0.0
    assert precision_at_k(RANKING, RELEVANT, 2) == 1 / 2
    assert precision_at_k(RANKING, RELEVANT, 5) == 2 / 5


def test_precision_counts_missing_results_as_wrong() -> None:
    assert precision_at_k(["a"], RELEVANT, 4) == 1 / 4


def test_recall_at_k() -> None:
    assert recall_at_k(RANKING, RELEVANT, 1) == 0.0
    assert recall_at_k(RANKING, RELEVANT, 2) == 1 / 2
    assert recall_at_k(RANKING, RELEVANT, 5) == 1.0


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(RANKING, RELEVANT) == 1 / 2
    assert reciprocal_rank(["x", "c"], RELEVANT) == 0.0


def test_ndcg_uses_grades() -> None:
    # gains 2^g-1: a=3, c=1, b=3 at ranks 2, 3, 5; the ideal order is 3, 3, 1.
    dcg = 3 / math.log2(3) + 1 / math.log2(4) + 3 / math.log2(6)
    ideal = 3 / math.log2(2) + 3 / math.log2(3) + 1 / math.log2(4)
    assert ndcg_at_k(RANKING, RELEVANT, 5) == pytest.approx(dcg / ideal)
    assert dcg / ideal == pytest.approx(0.65, abs=0.01)
    assert ndcg_at_k(["a", "b", "c"], RELEVANT, 3) == 1.0


def test_a_repeated_document_is_an_error() -> None:
    with pytest.raises(ValueError, match="repeated"):
        recall_at_k(["a", "a"], RELEVANT, 2)


def test_a_query_without_relevant_documents_is_an_error() -> None:
    with pytest.raises(ValueError, match="relevant"):
        recall_at_k(["a"], {"c": 1}, 1)


def test_match_scores() -> None:
    expected = {"s1": {"a", "b"}, "s2": {"c"}}
    actual = {"s1": {"a", "x"}, "s2": set(), "s3": {"y"}}
    scores = match_scores(expected, actual)
    # 1 true positive, 2 false positives (x, y), 2 misses (b, c)
    assert scores == {"precision": 1 / 3, "recall": 1 / 3, "true_positives": 1, "false_positives": 2, "misses": 2}


def test_match_scores_with_no_matches_has_no_division_by_zero() -> None:
    scores = match_scores({"s": {"a"}}, {})
    assert scores["precision"] == 0.0 and scores["recall"] == 0.0


def test_percentile_is_nearest_rank() -> None:
    values = [15.0, 20.0, 35.0, 40.0, 50.0]
    assert percentile(values, 50) == 35.0
    assert percentile(values, 95) == 50.0
    assert percentile(values, 5) == 15.0
    assert percentile(list(range(1, 101)), 99) == 99


def test_mean_of_nothing_is_an_error() -> None:
    with pytest.raises(ValueError):
        mean([])
