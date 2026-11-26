"""Many distinct subscriptions and long documents, for the scale run of the
matching engine. Apart from `corpus.py`, so that its output does not change."""
from __future__ import annotations

import random
from collections.abc import Iterator

from src.ingestor.fragmenter import fragmentar_texto
from src.synthetic.corpus import (
    BODIES,
    MONTHS,
    QUERIES,
    STREETS,
    SURNAMES,
    Corpus,
    Subscription,
    _filters_for,
    _topics,
)
from src.synthetic.lexicon import VOCABULARIES


def generate_subscriptions(corpus: Corpus, count: int) -> Iterator[Subscription]:
    """What somebody may ask to be told about: a topic, and often more detail
    (who, where, when). The filters are drawn from documents of the corpus."""
    config = corpus.config
    rng = random.Random(f"{config.seed}:{config.profile}:many-subscriptions")
    topics = _topics(random.Random(f"{config.seed}:{config.profile}:setup"), corpus.profile, config.documents)
    for i in range(count):
        topic = rng.choice(topics)
        text = rng.choice(QUERIES).format(**topic.words(rng.randrange(VOCABULARIES)))
        details = [
            f"de {rng.choice(BODIES)}",
            f"calle {rng.choice(STREETS)} {rng.randrange(100, 5000)}",
            f"firmado por {rng.choice(SURNAMES)} y {rng.choice(SURNAMES)}",
            f"antes de {rng.choice(MONTHS)}",
            f"expediente {rng.randrange(1000, 100_000)}",
        ]
        text = " ".join([text, *rng.sample(details, rng.randrange(0, 4))])
        filters = _filters_for(rng, corpus.profile, corpus.documents) if rng.random() < 0.6 else {}
        yield Subscription(f"m{i:07d}", text, filters, [])


def generate_long_documents(corpus: Corpus, *, count: int, fragments: int) -> list[tuple[dict, list[str]]]:
    """(metadata, fragment texts) of documents made of many notices on different
    topics, like a section that could not be split. The hardest to match: the
    fragments have little in common."""
    rng = random.Random(f"{corpus.config.seed}:long-documents")
    result = []
    for _ in range(count):
        first = rng.choice(corpus.documents)
        text, texts = first.texto, []
        while len(texts) < fragments:
            text += "\n" + rng.choice(corpus.documents).texto
            texts = fragmentar_texto(text)
        result.append((dict(first.metadata), texts[:fragments]))
    return result
