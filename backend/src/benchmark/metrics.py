"""Retrieval and matching metrics. Small on purpose: tested against values
computed by hand. Only exact documents count as relevant, except in nDCG, which
also uses the lower grade."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

RELEVANT_GRADE = 2


def _relevant(grades: Mapping[str, int]) -> set[str]:
    ids = {i for i, grade in grades.items() if grade >= RELEVANT_GRADE}
    if not ids:
        raise ValueError("the query has no relevant documents")
    return ids


def _top(ranking: Sequence[str], k: int) -> Sequence[str]:
    top = ranking[:k]
    if len(set(top)) != len(top):
        raise ValueError("repeated document in a ranking")
    return top


def precision_at_k(ranking: Sequence[str], grades: Mapping[str, int], k: int) -> float:
    """Divided by k, also when fewer results came back."""
    return len(_relevant(grades).intersection(_top(ranking, k))) / k


def recall_at_k(ranking: Sequence[str], grades: Mapping[str, int], k: int) -> float:
    relevant = _relevant(grades)
    return len(relevant.intersection(_top(ranking, k))) / len(relevant)


def reciprocal_rank(ranking: Sequence[str], grades: Mapping[str, int]) -> float:
    relevant = _relevant(grades)
    for position, identifier in enumerate(ranking, start=1):
        if identifier in relevant:
            return 1 / position
    return 0.0


def _dcg(grades: Sequence[int]) -> float:
    return sum((2**grade - 1) / math.log2(position + 1) for position, grade in enumerate(grades, start=1))


def ndcg_at_k(ranking: Sequence[str], grades: Mapping[str, int], k: int) -> float:
    _relevant(grades)
    ideal = _dcg(sorted(grades.values(), reverse=True)[:k])
    return _dcg([grades.get(i, 0) for i in _top(ranking, k)]) / ideal


def match_scores(expected: Mapping[str, set[str]], actual: Mapping[str, set[str]]) -> dict[str, float]:
    """Precision and recall over all (subscription, document) pairs."""
    wanted = {(s, d) for s, documents in expected.items() for d in documents}
    found = {(s, d) for s, documents in actual.items() for d in documents}
    hits = len(wanted & found)
    return {
        "precision": hits / len(found) if found else 0.0,
        "recall": hits / len(wanted) if wanted else 0.0,
        "true_positives": hits,
        "false_positives": len(found - wanted),
        "misses": len(wanted - found),
    }


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile: always one of the measured values."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("mean of no values")
    return math.fsum(values) / len(values)
