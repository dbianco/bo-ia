"""Plan 3: the indexed engine against the loop over every subscription."""
import random

import numpy as np
import pytest

from src.matching.subscription_index import SubscriptionIndex
from src.search.filters import cumple_filtros
from tests.vector.test_hnsw import unit

DIM = 24
THRESHOLD = 0.5


class Reference:
    """The obviously correct one: looks at everything."""

    def __init__(self) -> None:
        self.stored: dict[int, tuple[np.ndarray, dict, bool]] = {}

    def match(self, metadata: dict, fragments: np.ndarray, threshold: float) -> dict[int, float]:
        matches = {}
        for identifier, (vector, filters, active) in self.stored.items():
            if active and cumple_filtros(metadata, filters):
                score = max(float(np.dot(f, vector)) for f in fragments)
                if score >= threshold:
                    matches[identifier] = score
        return matches


def _filters(rng: random.Random) -> dict:
    filters = {}
    if rng.random() < 0.5:
        filters["provincia"] = {"tipo": "seleccion", "valor": rng.choice(["Córdoba", "San Luis", "Santa Fe"])}
    if rng.random() < 0.3:
        filters["monto"] = {"tipo": "rango_numerico", "valor": rng.choice(["10,50", "40,", ",30"])}
    return filters


def _metadata(rng: random.Random) -> dict:
    return {"provincia": rng.choice(["Córdoba", "San Luis", "Santa Fe"]), "monto": rng.randrange(80)}


def _assert_same(found: dict[int, float], expected: dict[int, float]) -> None:
    assert found.keys() == expected.keys()
    for identifier, score in expected.items():
        assert found[identifier] == pytest.approx(score, abs=1e-5)


def _clear_of_threshold(vectors: np.ndarray, fragments: np.ndarray) -> bool:
    """Leaves out of the comparison the ties that only rounding decides."""
    return bool((np.abs((vectors @ fragments.T).max(axis=1) - THRESHOLD) > 1e-5).all())


@pytest.mark.parametrize("graph_from", [0, 10_000], ids=["graph", "exact"])
@pytest.mark.parametrize("seed", range(12))
def test_random_subscriptions_and_documents_match_as_in_the_reference(seed: int, graph_from: int) -> None:
    rng, numbers = random.Random(seed), np.random.default_rng(seed)
    count = rng.choice([1, 5, 60, 300])
    # With a graph, search as wide as the set: the property is about the engine, not about approximation.
    index = SubscriptionIndex(DIM, graph_from=graph_from, exact_below=0 if graph_from == 0 else None, ef=400)
    reference = Reference()
    vectors = unit(numbers, count, DIM, clusters=4)
    for i, vector in enumerate(vectors):
        filters = _filters(rng)
        index.add(100 + i, vector, filters)
        reference.stored[100 + i] = (vector, filters, True)
    for _ in range(20):
        fragments = unit(numbers, rng.randrange(1, 6), DIM, clusters=4)
        if rng.random() < 0.7:
            fragments[0] = vectors[rng.randrange(count)]
        if not _clear_of_threshold(vectors, fragments):
            continue
        metadata = _metadata(rng)
        _assert_same(index.match(metadata, fragments, THRESHOLD), reference.match(metadata, fragments, THRESHOLD))


@pytest.mark.parametrize("graph_from", [0, 10_000], ids=["graph", "exact"])
@pytest.mark.parametrize("seed", range(8))
def test_any_sequence_of_changes_equals_an_index_built_from_scratch(seed: int, graph_from: int) -> None:
    rng, numbers = random.Random(seed), np.random.default_rng(seed)
    options = {"graph_from": graph_from, "exact_below": 0 if graph_from == 0 else None, "ef": 400}
    index, reference = SubscriptionIndex(DIM, **options), Reference()
    pool = unit(numbers, 200, DIM, clusters=3)
    for step in range(400):
        identifier = rng.randrange(80)
        known = reference.stored.get(identifier)
        action = rng.choice(["add", "pause", "resume", "delete", "change"])
        if action == "add" and known is None:
            vector, filters = pool[rng.randrange(200)], _filters(rng)
            index.add(identifier, vector, filters)
            reference.stored[identifier] = (vector, filters, True)
        elif action in ("pause", "resume") and known:
            index.set_active(identifier, action == "resume")
            reference.stored[identifier] = (known[0], known[1], action == "resume")
        elif action == "delete" and known:
            index.remove(identifier)
            del reference.stored[identifier]
        elif action == "change" and known:
            vector, filters = pool[rng.randrange(200)], _filters(rng)
            index.add(identifier, vector, filters, active=known[2])
            reference.stored[identifier] = (vector, filters, known[2])
        if step % 40 == 39:
            fresh = SubscriptionIndex(DIM, **options)
            for i, (vector, filters, active) in reference.stored.items():
                fresh.add(i, vector, filters, active=active)
            fragments = pool[rng.sample(range(200), 3)]
            if not _clear_of_threshold(pool, fragments):
                continue
            metadata = _metadata(rng)
            expected = reference.match(metadata, fragments, THRESHOLD)
            _assert_same(index.match(metadata, fragments, THRESHOLD), expected)
            _assert_same(fresh.match(metadata, fragments, THRESHOLD), expected)
            assert len(index) == len(fresh) == len(reference.stored)


def test_deleted_subscriptions_do_not_pile_up() -> None:
    numbers = np.random.default_rng(1)
    index = SubscriptionIndex(DIM, graph_from=0, compact_from=50)
    keep = unit(numbers, 20, DIM)
    index.add_many([(i, v, {}, True) for i, v in enumerate(keep)])
    for _ in range(10):
        index.add_many([(1000 + i, v, {}, True) for i, v in enumerate(unit(numbers, 100, DIM))])
        for i in range(100):
            index.remove(1000 + i)
    assert len(index) == 20
    assert index.rows <= 220, "removed rows must be dropped now and then"
    for i, vector in enumerate(keep):
        assert i in index.match({}, vector[None], 0.99)


def test_selective_filters_are_exact_whatever_the_graph_does() -> None:
    """Few subscriptions pass the filter and none is near the entry of the graph."""
    numbers = np.random.default_rng(4)
    index = SubscriptionIndex(DIM, graph_from=0)
    vectors = unit(numbers, 4000, DIM, clusters=30)
    rare = set(range(0, 4000, 400))
    index.add_many(
        [(i, v, {"provincia": {"tipo": "seleccion", "valor": "rare" if i in rare else "common"}}, True)
         for i, v in enumerate(vectors)]
    )
    for fragment in vectors[1:200:7]:
        truth = {i for i in rare if float(vectors[i] @ fragment) >= 0.2}
        assert set(index.match({"provincia": "rare"}, fragment[None], 0.2)) == truth


def test_recall_and_precision_with_a_graph_and_long_documents() -> None:
    rng, numbers = random.Random(2), np.random.default_rng(2)
    index, reference = SubscriptionIndex(DIM, graph_from=0, exact_below=0), Reference()
    vectors = unit(numbers, 5000, DIM, clusters=60)
    items = [(i, v, _filters(rng), True) for i, v in enumerate(vectors)]
    index.add_many(items)
    reference.stored = {i: (v, f, a) for i, v, f, a in items}
    wanted = found = hits = 0
    for _ in range(15):
        metadata, fragments = _metadata(rng), unit(numbers, 20, DIM, clusters=60)
        expected, actual = reference.match(metadata, fragments, 0.45), index.match(metadata, fragments, 0.45)
        wanted, found, hits = wanted + len(expected), found + len(actual), hits + len(expected.keys() & actual.keys())
        for i in expected.keys() & actual.keys():
            assert actual[i] == pytest.approx(expected[i], abs=1e-5), "the score is the best of all the fragments"
    assert wanted > 500
    assert hits == found, "precision 1.0"
    assert hits / wanted >= 0.99


def test_vectors_are_normalized_and_zero_vectors_match_nothing() -> None:
    index = SubscriptionIndex(3)
    index.add(1, [2.0, 0.0, 0.0], {})
    index.add(2, [0.0, 0.0, 0.0], {})
    assert index.match({}, np.array([[10.0, 0.0, 0.0]]), 0.5) == {1: pytest.approx(1.0)}
    assert index.match({}, np.zeros((1, 3)), 0.1) == {}


def test_a_document_without_fragments_matches_nothing() -> None:
    index = SubscriptionIndex(3)
    index.add(1, [1.0, 0.0, 0.0], {})
    assert index.match({}, np.zeros((0, 3)), -1.0) == {}


def test_unknown_subscriptions() -> None:
    index = SubscriptionIndex(3)
    index.remove(5)  # already gone: deleting twice is not an error
    with pytest.raises(KeyError):
        index.set_active(5, True)
    assert 5 not in index
