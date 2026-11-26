"""Plan 4: the three rankings put together, without a database."""
import datetime
import random

import numpy as np
import pytest

from src.config.installation import FiltroSeleccion
from src.engine.engine import EngineFragment, SearchEngine
from src.processor.hashed_embeddings import HashedEmbeddingProvider
from src.processor.hybrid import fusionar_rrf
from tests.vector.test_hnsw import unit

DIM = 8
DECLARED = [FiltroSeleccion(clave="provincia", etiqueta="Provincia")]
DAY = datetime.date(2026, 1, 1)


def axis(weight: float) -> list[float]:
    return [weight, (1 - weight * weight) ** 0.5] + [0.0] * (DIM - 2)


QUERY = np.array(axis(1.0), dtype=np.float32)


@pytest.fixture()
def engine() -> SearchEngine:
    engine = SearchEngine(DIM)
    texts = {1: ("puente vehicular", 0.9), 2: ("escuela rural", 0.7), 3: ("puente ferroviario", 0.3), 4: ("plaza", 0.2)}
    for i, (text, weight) in texts.items():
        engine.put(i, DAY + datetime.timedelta(days=i), {"provincia": "A" if i % 2 else "B"},
                   [EngineFragment(i * 10, text, axis(weight))])  # fmt: skip
    return engine


def search(engine: SearchEngine, text: str = "puente", mode: str = "semantic", **options):
    options.setdefault("threshold", 0.5)
    return engine.search(text, QUERY, mode=mode, limit=options.pop("limit", 10), **options)


def ids(hits) -> list[int]:
    return [hit.fragment_id for hit in hits]


def test_semantic_keeps_what_reaches_the_threshold_in_order(engine) -> None:
    hits = search(engine)
    assert ids(hits) == [10, 20]
    assert [round(h.similarity, 4) for h in hits] == [0.9, 0.7]
    assert not any(h.text_match for h in hits)
    assert [h.document_id for h in hits] == [1, 2]


def test_hybrid_rescues_text_matches_below_the_threshold(engine) -> None:
    hits = search(engine, mode="hybrid")
    assert set(ids(hits)) == {10, 20, 30}
    assert ids(hits)[0] == 10, "in both rankings"
    assert {h.fragment_id for h in hits if h.text_match} == {10, 30}
    assert round(next(h for h in hits if h.fragment_id == 30).similarity, 4) == 0.3


def test_a_text_match_needs_every_word_as_until_now(engine) -> None:
    assert set(ids(search(engine, "puente ferroviario", mode="hybrid"))) == {10, 20, 30}
    assert set(ids(search(engine, "puente inexistente", mode="hybrid"))) == {10, 20}


def test_all_has_no_threshold(engine) -> None:
    assert set(ids(search(engine, mode="all"))) == {10, 20, 30, 40}


def test_the_limit_applies_at_the_end(engine) -> None:
    assert ids(search(engine, limit=1)) == [10]
    assert len(search(engine, mode="all", limit=2)) == 2


def test_filters_and_dates(engine) -> None:
    def found(**options):
        return set(ids(search(engine, mode="all", filters_declared=DECLARED, **options)))

    assert found(filters={"provincia": "A"}) == {10, 30}
    assert found(date_from=DAY + datetime.timedelta(days=3)) == {30, 40}
    assert found(filters={"provincia": "A"}, date_to=DAY + datetime.timedelta(days=1)) == {10}
    assert found(filters={"provincia": "none"}) == set()


def test_fusion_is_the_one_that_was_used_until_now(engine) -> None:
    hits = search(engine, mode="all")
    scores = fusionar_rrf([10, 20, 30, 40], [10, 30])
    assert ids(hits) == sorted(scores, key=lambda i: -scores[i])


def test_fusion_weights() -> None:
    engine = SearchEngine(DIM, fusion_weights=(1.0, 10.0))
    engine.put(1, DAY, {}, [EngineFragment(10, "plaza", axis(0.9))])
    engine.put(2, DAY, {}, [EngineFragment(20, "puente", axis(0.6))])
    assert ids(search(engine, mode="hybrid")) == [20, 10]
    assert fusionar_rrf([1, 2], [2], pesos=(0.0, 1.0))[1] == 0.0


def test_documents_can_be_replaced_updated_and_removed(engine) -> None:
    engine.put(1, DAY, {"provincia": "B"}, [EngineFragment(11, "plaza central", axis(0.95))])
    assert ids(search(engine)) == [11, 20]
    assert 11 in ids(search(engine, "plaza", mode="hybrid")) and 10 not in ids(search(engine, mode="all"))
    engine.update(2, DAY, {"provincia": "A"})
    assert ids(search(engine, filters={"provincia": "A"}, filters_declared=DECLARED)) == [20]
    engine.remove(1)
    engine.remove(999)
    assert ids(search(engine)) == [20]
    assert len(engine) == 3


def test_fragments_without_vector_are_found_by_text_only(engine) -> None:
    engine.put(9, DAY, {}, [EngineFragment(90, "represa hidroeléctrica", None)])
    assert 90 not in ids(search(engine, "represa", mode="semantic", threshold=-1.0))
    (hit,) = [h for h in search(engine, "represa", mode="hybrid") if h.text_match]
    assert hit.fragment_id == 90 and hit.similarity == 0.0


def test_a_document_with_many_fragments_may_give_many_results(engine) -> None:
    engine.put(5, DAY, {}, [EngineFragment(50 + i, "puente", axis(0.8)) for i in range(3)])
    assert ids(search(engine)) == [10, 50, 51, 52, 20]


def test_an_empty_engine() -> None:
    engine = SearchEngine(DIM)
    for mode in ("semantic", "hybrid", "all"):
        assert search(engine, mode=mode) == []


def test_removed_documents_do_not_pile_up() -> None:
    engine = SearchEngine(DIM, compact_from=40)
    for round_ in range(6):
        for i in range(30):
            engine.put(i, DAY, {}, [EngineFragment(1000 * round_ + i, f"puente {round_}", axis(0.9))])
    assert len(engine) == 30 and engine.rows <= 100
    assert sorted(ids(search(engine, limit=50))) == [5000 + i for i in range(30)]
    assert sorted(ids(search(engine, "puente", mode="hybrid", limit=50))) == [5000 + i for i in range(30)]


@pytest.mark.parametrize("seed", range(6))
def test_random_histories_equal_an_engine_built_from_scratch(seed: int) -> None:
    rng, numbers = random.Random(seed), np.random.default_rng(seed)
    vectors, words = unit(numbers, 300, DIM), ["puente", "escuela", "plaza", "ruta", "hospital"]
    engine, stored, serial = SearchEngine(DIM, compact_from=30), {}, 0
    for step in range(150):
        i = rng.randrange(25)
        if rng.random() < 0.7:
            fragments = []
            for _ in range(rng.randrange(1, 4)):
                serial += 1
                fragments.append(EngineFragment(serial, " ".join(rng.choices(words, k=3)), vectors[rng.randrange(300)]))
            stored[i] = (DAY + datetime.timedelta(days=rng.randrange(9)), {"provincia": rng.choice("AB")}, fragments)
            engine.put(i, *stored[i])
        else:
            stored.pop(i, None)
            engine.remove(i)
        if step % 25 == 24:
            fresh = SearchEngine(DIM)
            for j, document in sorted(stored.items()):
                fresh.put(j, *document)
            for mode in ("semantic", "hybrid", "all"):
                options = {"mode": mode, "filters": {"provincia": "A"}, "filters_declared": DECLARED, "limit": 200,
                           "threshold": 0.3}  # fmt: skip
                query = vectors[rng.randrange(300)]
                a, b = (e.search("puente escuela", query, **options) for e in (engine, fresh))
                # Equal scores may come in another order, as rows are numbered by arrival.
                key = lambda h: (h.fragment_id, h.document_id, round(h.similarity, 5), h.text_match)  # noqa: E731
                assert sorted(map(key, a)) == sorted(map(key, b))


def test_hybrid_is_not_worse_than_its_parts_on_paraphrases() -> None:
    from src.benchmark.harness import evaluate_search
    from src.benchmark.systems import EngineSearch
    from src.synthetic.corpus import CorpusConfig, generate_corpus

    corpus = generate_corpus(CorpusConfig(seed=17, documents=1200))
    provider = HashedEmbeddingProvider(synonyms=corpus.synonym_table(0.8))
    engine = EngineSearch.build(corpus.documents, provider, corpus.profile.filters)
    score = {
        mode: evaluate_search(engine.with_mode(mode, threshold=0.45), corpus)[0]["paraphrase"]["ndcg@10"]
        for mode in ("lexical", "semantic", "hybrid")
    }
    assert score["semantic"] > score["lexical"]
    assert score["hybrid"] >= max(score["lexical"], score["semantic"])
