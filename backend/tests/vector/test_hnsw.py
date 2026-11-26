"""The vector index shared by plans 3 and 4, against an exact scan."""
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from src.vector import hnsw
from src.vector.hnsw import VectorIndex

DIM = 48


def unit(rng: np.random.Generator, count: int, dim: int = DIM, clusters: int = 0) -> np.ndarray:
    rows = rng.normal(size=(count, dim))
    if clusters:
        centers = rng.normal(size=(clusters, dim)) * 2
        rows = rows * 0.8 + centers[rng.integers(clusters, size=count)]
    return (rows / np.linalg.norm(rows, axis=1, keepdims=True)).astype(np.float32)


def exact_top(vectors: np.ndarray, query: np.ndarray, k: int, allowed=None) -> list[int]:
    sims = vectors @ query
    rows = np.arange(len(vectors)) if allowed is None else np.flatnonzero(allowed)
    return rows[np.lexsort((rows, -sims[rows]))][:k].tolist()


@pytest.fixture(scope="module")
def data():
    rng = np.random.default_rng(7)
    vectors = unit(rng, 6100, clusters=40)
    index = VectorIndex(DIM, graph_from=0)
    index.add(vectors[:6000])
    return vectors[:6000], vectors[6000:], index


def recall(index, vectors, queries, k=10, allowed=None, **options) -> float:
    hits = wanted = 0
    for query in queries:
        rows, _ = index.search(query, k, allowed=allowed, **options)
        truth = exact_top(vectors, query, k, allowed)
        hits += len(set(rows.tolist()) & set(truth))
        wanted += len(truth)
    return hits / wanted


def test_recall_without_filters(data) -> None:
    vectors, queries, index = data
    assert index.graph_rows == 6000
    assert recall(index, vectors, queries, ef=100) >= 0.97


def test_recall_grows_with_the_search_width(data) -> None:
    vectors, queries, index = data
    curve = [recall(index, vectors, queries, ef=ef) for ef in (10, 40, 400)]
    assert curve == sorted(curve) and curve[2] >= 0.995


def test_results_are_ordered_and_similarities_are_exact(data) -> None:
    vectors, queries, index = data
    rows, sims = index.search(queries[0], 20)
    assert sims.tolist() == sorted(sims.tolist(), reverse=True)
    assert np.allclose(sims, vectors[rows] @ queries[0], atol=1e-6)
    assert len(set(rows.tolist())) == 20


@pytest.mark.parametrize("share", [0.5, 0.2, 0.05, 0.01, 0.001])
def test_recall_under_filters(data, share: float) -> None:
    vectors, queries, index = data
    allowed = (np.random.default_rng(1).random(len(vectors)) < share).astype(np.uint8)
    assert recall(index, vectors, queries, allowed=allowed) >= 0.95
    # Also when the traversal has to do it, without the exact scan.
    if share >= 0.05:
        assert recall(index, vectors, queries, allowed=allowed, exact_below=0, ef=200) >= 0.95


def test_a_filter_correlated_with_the_query_region(data) -> None:
    """All the allowed rows are far away from the query: the usual failure of
    filtering during the traversal."""
    vectors, queries, index = data
    for query in queries[:20]:
        allowed = (vectors @ query < np.quantile(vectors @ query, 0.02)).astype(np.uint8)
        rows, _ = index.search(query, 10, allowed=allowed)
        assert rows.tolist() == exact_top(vectors, query, 10, allowed)


def test_only_allowed_rows_are_returned(data) -> None:
    vectors, queries, index = data
    allowed = np.zeros(len(vectors), dtype=np.uint8)
    allowed[::3] = 1
    for exact_below in (0, None):
        rows, _ = index.search(queries[0], 50, allowed=allowed, exact_below=exact_below)
        assert len(rows) == 50 and (rows % 3 == 0).all()


def test_nothing_allowed(data) -> None:
    _, queries, index = data
    rows, sims = index.search(queries[0], 5, allowed=np.zeros(6000, dtype=np.uint8))
    assert len(rows) == len(sims) == 0


@pytest.mark.parametrize("threshold", [0.9, 0.7, 0.5, 0.3])
def test_threshold_search_finds_every_row_however_many(data, threshold: float) -> None:
    vectors, queries, index = data
    found = expected = hits = 0
    for query in queries[:50]:
        truth = set(np.flatnonzero(vectors @ query >= threshold).tolist())
        rows, sims = index.search_threshold(query[None], threshold)
        assert np.allclose(sims, vectors[rows] @ query, atol=1e-6)
        assert (sims >= threshold).all()
        found += len(rows)
        expected += len(truth)
        hits += len(truth & set(rows.tolist()))
    assert found == hits, "precision"
    assert expected > 20
    assert hits / expected >= 0.99


def test_threshold_search_with_several_queries_keeps_the_best_score(data) -> None:
    vectors, queries, index = data
    group = queries[:8]
    best = (vectors @ group.T).max(axis=1)
    rows, sims = index.search_threshold(group, 0.5)
    truth = set(np.flatnonzero(best >= 0.5).tolist())
    assert len(truth & set(rows.tolist())) >= 0.99 * len(truth)
    assert len(set(rows.tolist())) == len(rows)
    assert np.allclose(sims, best[rows], atol=1e-6)


def test_threshold_search_under_a_filter(data) -> None:
    vectors, queries, index = data
    allowed = np.zeros(len(vectors), dtype=np.uint8)
    allowed[1::2] = 1
    for exact_below in (0, None):
        hits = expected = 0
        for query in queries[:40]:
            truth = set(np.flatnonzero((vectors @ query >= 0.5) & (allowed == 1)).tolist())
            rows, _ = index.search_threshold(query[None], 0.5, allowed=allowed, exact_below=exact_below)
            assert set(rows.tolist()) <= truth
            hits += len(rows)
            expected += len(truth)
        assert hits / expected >= 0.99


def test_top_k_with_a_threshold(data) -> None:
    vectors, queries, index = data
    for query in queries[:10]:
        rows, sims = index.search(query, 50, threshold=0.6, ef=200)
        assert (sims >= 0.6).all()
        plain, plain_sims = index.search(query, 50, ef=200)
        assert rows.tolist() == plain[plain_sims >= 0.6].tolist()


def test_rows_added_later_are_found() -> None:
    rng = np.random.default_rng(3)
    everything = unit(rng, 3050, clusters=20)
    vectors, queries = everything[:3000], everything[3000:]
    index = VectorIndex(DIM, graph_from=0)
    assert list(index.add(vectors[:10])) == list(range(10))
    for start in range(10, 3000, 173):
        index.add(vectors[start : start + 173])
    assert len(index) == 3000
    assert recall(index, vectors, queries, ef=100) >= 0.97
    own = [index.search(vectors[i], 1)[0][0] == i for i in range(0, 3000, 29)]
    assert sum(own) / len(own) >= 0.99


def test_rows_that_are_stored_and_not_linked_yet_are_found() -> None:
    """A search may come between the two."""
    rng = np.random.default_rng(13)
    vectors = unit(rng, 900)
    index = VectorIndex(DIM, graph_from=0)
    index.add(vectors[:800])
    index._store(vectors[800:])
    assert (index.graph_rows, len(index)) == (800, 900)
    for row in (800, 850, 899):
        assert index.search(vectors[row], 1, exact_below=0)[0].tolist() == [row]
        assert row in index.search_threshold(vectors[row][None], 0.99, exact_below=0)[0]
        allowed = np.ones(900, dtype=np.uint8)
        allowed[row] = 0
        assert row not in index.search(vectors[row], 5, allowed=allowed, exact_below=0)[0]
        assert row not in index.search_threshold(vectors[row][None], 0.99, allowed=allowed, exact_below=0)[0]


def test_one_row_at_a_time() -> None:
    rng = np.random.default_rng(5)
    vectors = unit(rng, 400)
    index = VectorIndex(DIM, graph_from=0)
    for vector in vectors:
        index.add(vector[None])
    assert recall(index, vectors, unit(rng, 30), ef=100) >= 0.95


def test_below_the_graph_size_the_search_is_exact_and_nothing_is_built() -> None:
    rng = np.random.default_rng(5)
    vectors = unit(rng, 500)
    index = VectorIndex(DIM, graph_from=1000)
    index.add(vectors)
    assert index.graph_rows == 0
    for query in unit(rng, 20):
        assert index.search(query, 10)[0].tolist() == exact_top(vectors, query, 10)
        truth = np.flatnonzero(vectors @ query >= 0.2)
        assert sorted(index.search_threshold(query[None], 0.2)[0].tolist()) == truth.tolist()
    index.add(unit(rng, 600))
    assert index.graph_rows == 1100


@pytest.mark.parametrize("threads", [1, 4])
def test_the_graph_does_not_depend_on_the_threads(monkeypatch, threads: int) -> None:
    vectors = unit(np.random.default_rng(11), 1500, clusters=5)
    reference = VectorIndex(DIM, graph_from=0, seed=3)
    reference.add(vectors)
    monkeypatch.setattr(hnsw, "THREADS", threads)
    other = VectorIndex(DIM, graph_from=0, seed=3)
    other.add(vectors)
    assert np.array_equal(reference._links0, other._links0)
    assert np.array_equal(reference._upper_links, other._upper_links)


def test_many_identical_vectors_do_not_cut_the_graph() -> None:
    """Subscriptions with the same text, republished notices."""
    rng = np.random.default_rng(9)
    distinct = unit(rng, 600)
    copies = np.repeat(distinct[:3], 400, axis=0)
    vectors = np.concatenate([copies, distinct])
    index = VectorIndex(DIM, graph_from=0)
    index.add(vectors)
    rows, _ = index.search_threshold(distinct[1][None], 0.999)
    assert set(rows.tolist()) >= set(range(400, 800))
    reached = [1200 + i in index.search(distinct[i], 1200, ef=1300)[0] for i in range(100, 600, 10)]
    assert sum(reached) / len(reached) >= 0.98


@pytest.mark.parametrize("count", [0, 1, 2])
def test_very_small_indexes(count: int) -> None:
    index = VectorIndex(DIM, graph_from=0)
    vectors = unit(np.random.default_rng(1), 3)
    index.add(vectors[:count])
    rows, _ = index.search(vectors[0], 10)
    assert sorted(rows.tolist()) == list(range(count))
    assert len(index.search_threshold(vectors[0][None], -1.0)[0]) == count


def test_wrong_shapes_are_rejected() -> None:
    index = VectorIndex(DIM)
    with pytest.raises(ValueError, match="dimension"):
        index.add(np.zeros((2, DIM + 1), dtype=np.float32))
    with pytest.raises(ValueError):
        VectorIndex(DIM, m=1)


def test_concurrent_searches(data) -> None:
    vectors, queries, index = data
    expected = [index.search(q, 10)[0].tolist() for q in queries]
    with ThreadPoolExecutor(8) as pool:
        found = list(pool.map(lambda q: index.search(q, 10)[0].tolist(), list(queries) * 5))
    assert found == expected * 5


def test_searching_while_rows_are_added() -> None:
    rng = np.random.default_rng(2)
    vectors = unit(rng, 3000)
    index = VectorIndex(DIM, graph_from=0)
    index.add(vectors[:500])
    errors: list[Exception] = []
    done = threading.Event()

    def search() -> None:
        try:
            while not done.is_set():
                for query in vectors[:50]:
                    rows, sims = index.search(query, 5)
                    assert len(rows) == 5 and np.allclose(sims, vectors[rows] @ query, atol=1e-5)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=search) for _ in range(3)]
    for thread in threads:
        thread.start()
    for start in range(500, 3000, 100):
        index.add(vectors[start : start + 100])
    done.set()
    for thread in threads:
        thread.join()
    assert errors == []
