"""The lexicon is what makes paraphrase queries hard: if two vocabularies of
one concept shared a word, lexical search would find documents it should not."""
from itertools import combinations

import pytest

from src.synthetic.lexicon import ASPECTS, FAMILIES, VOCABULARIES, all_concepts
from src.text.tokens import content_tokens, fold


def test_fold_removes_case_and_accents() -> None:
    assert fold("LICITACIÓN Pública Ñandú") == "licitacion publica nandu"


@pytest.mark.parametrize("concept", all_concepts(), ids=lambda c: c.key)
def test_vocabularies_of_a_concept_share_no_content_word(concept) -> None:
    assert len(concept.variants) == VOCABULARIES
    for a, b in combinations(concept.variants, 2):
        assert content_tokens(a), a
        assert not set(content_tokens(a)) & set(content_tokens(b)), (concept.key, a, b)


def test_no_phrase_names_two_concepts() -> None:
    phrases = [tuple(content_tokens(v)) for c in all_concepts() for v in c.variants]
    assert len(phrases) == len(set(phrases))


def test_concept_keys_are_unique_and_the_topic_space_is_large() -> None:
    keys = [c.key for c in all_concepts()]
    assert len(keys) == len(set(keys))
    assert sum(len(f.kinds) * len(f.subjects) for f in FAMILIES) * len(ASPECTS) >= 3000
