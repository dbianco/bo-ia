"""Plan 4: inverted index, BM25 and dynamic pruning."""
import math
import random

import numpy as np
import pytest

from src.engine.analyzer import analyze
from src.engine.lexical import LexicalIndex

K1, B = 1.2, 0.75


def bm25(tf: int, length: int, *, df: int, n: int, average: float) -> float:
    return math.log(1 + (n - df + 0.5) / (df + 0.5)) * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / average))


def build(texts: list[str], chunks: int = 1) -> LexicalIndex:
    index = LexicalIndex()
    size = max(1, math.ceil(len(texts) / chunks))
    for start in range(0, len(texts), size):
        index.add(texts[start : start + size])
    return index


def test_scores_equal_hand_computed_values() -> None:
    index = build(["puente puente camion", "puente ciudad largo norte", "escuela"])
    rows, scores = index.search("puente", 10)
    assert rows.tolist() == [0, 1]
    common = {"df": 2, "n": 3, "average": (3 + 4 + 1) / 3}
    assert scores.tolist() == pytest.approx([bm25(2, 3, **common), bm25(1, 4, **common)])


def test_scores_of_several_terms_add_up() -> None:
    index = build(["puente escuela", "puente", "escuela escuela hospital"])
    rows, scores = index.search("escuela puente", 10)
    average = (2 + 1 + 3) / 3
    expected = {
        0: bm25(1, 2, df=2, n=3, average=average) * 2,
        1: bm25(1, 1, df=2, n=3, average=average),
        2: bm25(2, 3, df=2, n=3, average=average),
    }
    assert dict(zip(rows.tolist(), scores.tolist(), strict=True)) == {r: pytest.approx(s) for r, s in expected.items()}


def test_a_repeated_query_word_counts_once() -> None:
    index = build(["puente escuela", "puente"])
    assert index.search("puente puente puentes", 5)[1].tolist() == index.search("puente", 5)[1].tolist()


def test_ties_go_to_the_first_row() -> None:
    index = build(["puente"] * 5)
    assert index.search("puente", 3)[0].tolist() == [0, 1, 2]


def test_all_the_words_or_any_of_them() -> None:
    index = build(["puente rural", "puente escuela rural", "escuela"])
    assert sorted(index.search("puente escuela", 10)[0].tolist()) == [0, 1, 2]
    assert index.search("puente escuela", 10, require_all=True)[0].tolist() == [1]


@pytest.mark.parametrize("query", ["", "de la", "inexistente"])
def test_queries_that_find_nothing(query: str) -> None:
    index = build(["puente"])
    for require_all in (False, True):
        rows, scores = index.search(query, 5, require_all=require_all)
        assert len(rows) == len(scores) == 0


def test_an_unknown_word() -> None:
    index = build(["puente", "escuela"])
    assert index.search("puente inexistente", 5)[0].tolist() == [0]
    assert len(index.search("puente inexistente", 5, require_all=True)[0]) == 0


def test_an_empty_index_and_empty_texts() -> None:
    assert len(LexicalIndex().search("puente", 5)[0]) == 0
    index = build(["", "puente", "de la"])
    assert index.search("puente", 5)[0].tolist() == [1]


def test_filters_are_applied_during_the_search() -> None:
    index = build([f"puente {'rural ' * i}" for i in range(200)])
    allowed = np.zeros(200, dtype=np.uint8)
    allowed[50::7] = 1
    rows, _ = index.search("puente", 5, allowed=allowed)
    assert rows.tolist() == [50, 57, 64, 71, 78]


WORDS = [f"palabra{i}x" for i in range(40)]


def _texts(rng: random.Random, count: int) -> list[str]:
    weights = [1 / (i + 1) for i in range(len(WORDS))]  # some words are everywhere and some are rare
    return [" ".join(rng.choices(WORDS, weights, k=rng.randrange(1, 60))) for _ in range(count)]


@pytest.mark.parametrize("require_all", [False, True], ids=["any", "all"])
@pytest.mark.parametrize("seed", range(15))
def test_the_pruned_top_equals_the_exhaustive_one(seed: int, require_all: bool) -> None:
    rng = random.Random(seed)
    count = rng.choice([50, 700, 4000])
    index = build(_texts(rng, count), chunks=rng.choice([1, 3, 10]))
    for _ in range(25):
        query = " ".join(rng.sample(WORDS, rng.randrange(1, 7)))
        k = rng.choice([1, 3, 10, 100, 10_000])
        allowed = None
        if rng.random() < 0.4:
            share = rng.choice([0.01, 0.3, 0.9])
            allowed = (np.random.default_rng(rng.randrange(10**6)).random(count) < share).astype(np.uint8)
        pruned = index.search(query, k, allowed=allowed, require_all=require_all)
        exhaustive = index.search_exhaustive(query, k, allowed=allowed, require_all=require_all)
        assert pruned[0].tolist() == exhaustive[0].tolist()
        assert pruned[1].tolist() == exhaustive[1].tolist(), "not even the last digit differs"


def _uneven_texts(rng: random.Random, count: int) -> list[str]:
    """Most rows are long and mention a word once; here and there a few short
    rows are full of one. So the bounds of the blocks are very different."""
    texts = []
    for row in range(count):
        if rng.random() < 0.01 or (row // 40) % 25 == 7 and rng.random() < 0.3:
            texts.append(" ".join([rng.choice(WORDS[:6])] * rng.randrange(2, 12)))
        else:
            texts.append(" ".join(rng.sample(WORDS[:6], rng.randrange(1, 4)) + ["relleno"] * rng.randrange(20, 60)))
    return texts


@pytest.mark.parametrize("require_all", [False, True], ids=["any", "all"])
@pytest.mark.parametrize("seed", range(10))
def test_skipping_stops_where_the_next_block_begins(seed: int, require_all: bool) -> None:
    rng = random.Random(seed)
    index = build(_uneven_texts(rng, 6000), chunks=rng.choice([1, 2]))
    scored = postings = 0
    for _ in range(30):
        query = " ".join(rng.sample(WORDS[:6], rng.randrange(1, 4)))
        k = rng.choice([1, 2, 5, 20, 100])
        pruned = index.search(query, k, require_all=require_all)
        scored += index.last_scored
        postings += index.postings(query)
        exhaustive = index.search_exhaustive(query, k, require_all=require_all)
        assert pruned[0].tolist() == exhaustive[0].tolist() and pruned[1].tolist() == exhaustive[1].tolist()
    assert scored < 0.8 * postings, "nothing was skipped, so nothing was tested"


def test_exhaustive_search_equals_a_direct_computation() -> None:
    rng = random.Random(3)
    texts = _texts(rng, 300)
    index = build(texts, chunks=4)
    terms = [analyze(t) for t in texts]
    average = sum(map(len, terms)) / len(terms)
    for _ in range(10):
        query = rng.sample(WORDS, 4)
        expected = {}
        for row, words in enumerate(terms):
            score = 0.0
            for word in sorted({analyze(q)[0] for q in query}):
                tf, df = words.count(word), sum(word in t for t in terms)
                if tf:
                    score += bm25(tf, len(words), df=df, n=len(terms), average=average)
            if score:
                expected[row] = score
        rows, scores = index.search_exhaustive(" ".join(query), 1000)
        assert dict(zip(rows.tolist(), scores.tolist(), strict=True)) == {
            r: pytest.approx(s) for r, s in expected.items()
        }


def test_pruning_skips_work() -> None:
    rng = random.Random(1)
    texts = _texts(rng, 20_000)
    texts[100] = "rarisima " * 30
    index = build(texts)
    index.search(f"rarisima {WORDS[0]}", 1)
    assert index.last_scored < 0.2 * index.postings(f"rarisima {WORDS[0]}")


def test_results_do_not_depend_on_how_the_documents_arrived() -> None:
    texts = _texts(random.Random(8), 1500)
    whole, pieces, one_by_one = build(texts), build(texts, chunks=13), build(texts[:400], chunks=400)
    one_by_one.add(texts[400:])
    for query in (" ".join(WORDS[:3]), WORDS[20], " ".join(WORDS[10:16])):
        expected = whole.search(query, 20)
        for other in (pieces, one_by_one):
            rows, scores = other.search(query, 20)
            assert rows.tolist() == expected[0].tolist() and scores.tolist() == expected[1].tolist()
    assert one_by_one.segments <= 12, "small segments are merged as they pile up"


def test_statistics_are_global_and_current() -> None:
    """Scores of the first documents change when others arrive."""
    index = build(["puente", "escuela"])
    before = index.search("puente", 1)[1][0]
    index.add(["puente puente"] * 10)
    after = index.search("puente", 20)
    assert after[1][after[0].tolist().index(0)] != before
