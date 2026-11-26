"""Plan 3: many distinct subscriptions and long documents for the scale run."""
from src.synthetic.corpus import CorpusConfig, generate_corpus, satisfies_filters
from src.synthetic.subscriptions import generate_long_documents, generate_subscriptions


def _corpus():
    return generate_corpus(CorpusConfig(seed=6, documents=600))


def test_subscriptions_are_deterministic_and_mostly_distinct() -> None:
    corpus = _corpus()
    a, b = (list(generate_subscriptions(corpus, 3000)) for _ in range(2))
    assert a == b and len(a) == 3000
    assert len({s.id for s in a}) == 3000
    assert len({s.text for s in a}) > 2500, "few texts would make few vectors"
    share = sum(1 for s in a if s.filters) / len(a)
    assert 0.4 < share < 0.8
    assert list(generate_subscriptions(corpus, 100)) == a[:100], "a larger run extends a smaller one"


def test_filters_are_satisfied_by_some_document() -> None:
    corpus = _corpus()
    subscriptions = list(generate_subscriptions(corpus, 300))
    for subscription in subscriptions:
        assert any(satisfies_filters(d.metadata, subscription.filters) for d in corpus.documents)


def test_long_documents_have_the_requested_fragments() -> None:
    corpus = _corpus()
    documents = generate_long_documents(corpus, count=5, fragments=20)
    assert [len(texts) for _, texts in documents] == [20] * 5
    assert documents == generate_long_documents(corpus, count=5, fragments=20)
    assert all(metadata for metadata, _ in documents)
