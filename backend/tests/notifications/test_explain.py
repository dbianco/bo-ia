"""Plan 10: what matched and why."""
import random

import pytest

from src.notifications.explain import EXCERPT_LENGTH, excerpt_of, highlight, shared_words


def parts(text: str, query: str) -> str:
    """The text with the shared words between brackets."""
    return "".join(f"[{p.text}]" if p.match else p.text for p in highlight(text, query))


@pytest.mark.parametrize(
    ("text", "query", "expected"),
    [
        ("Licitación para pavimentar", "licitaciones", "[Licitación] para pavimentar"),
        ("obra PÚBLICA y obras públicas", "pública", "obra [PÚBLICA] y obras [públicas]"),
        ("El puente, el puente.", "puentes", "El [puente], el [puente]."),
        ("de la obra", "de la casa", "de la obra"),
        ("Expediente 0683-080515", "080515", "Expediente 0683-[080515]"),
        ("nada en común", "otra cosa", "nada en común"),
        ("", "x", ""),
        ("calle", "", "calle"),
        ("ñandú\ncalle", "calle nandu", "[ñandú]\n[calle]"),
    ],
)
def test_shared_words_are_marked(text, query, expected) -> None:
    assert parts(text, query) == expected


def test_nothing_of_the_text_is_lost_or_added() -> None:
    rng = random.Random(1)
    alphabet = "abcñÁé <>&\"'\n\t-.,0123 licitación calle "
    for _ in range(200):
        text = "".join(rng.choices(alphabet, k=rng.randrange(0, 200)))
        assert "".join(p.text for p in highlight(text, "licitación calle abc")) == text


def test_the_shared_words_as_they_are_written_in_the_document() -> None:
    assert shared_words("Licitación pública. LICITACIÓN de obra", "licitaciones de obras") == ["Licitación", "obra"]
    assert shared_words("Suministro de gasoil", "compra de combustible") == []


def test_a_short_fragment_is_its_own_excerpt() -> None:
    assert excerpt_of("Texto corto.", "algo") == "Texto corto."


def test_the_excerpt_is_part_of_the_text_and_has_the_shared_words() -> None:
    filler = "Relleno sin relación alguna con el pedido. " * 12
    text = filler + "Se llama a licitación para la pavimentación de calles. " + filler
    excerpt = excerpt_of(text, "pavimentación de calles")
    assert excerpt in text and "pavimentación de calles" in excerpt
    assert len(excerpt) <= EXCERPT_LENGTH
    assert not excerpt[0].isspace() and not excerpt[-1].isspace()


def test_without_shared_words_it_is_the_beginning() -> None:
    text = "Uno dos tres. " * 100
    excerpt = excerpt_of(text, "zapatos")
    assert text.startswith(excerpt) and 100 < len(excerpt) <= EXCERPT_LENGTH


def test_words_are_not_cut() -> None:
    rng = random.Random(3)
    words = ["pavimentación", "calle", "obra", "ministerio", "x", "licitación"]
    for _ in range(100):
        text = " ".join(rng.choices(words, k=rng.randrange(1, 200)))
        excerpt = excerpt_of(text, rng.choice(words))
        assert f" {excerpt} " in f" {text} "


def test_a_text_without_spaces_is_cut_all_the_same() -> None:
    assert len(excerpt_of("x" * 5000, "y")) <= EXCERPT_LENGTH


@pytest.mark.parametrize("backend", ["loop", "indexed"])
def test_matching_records_the_best_fragment(db_session, backend, make) -> None:
    from src.db.models import EvaluacionMatch, Fragmento
    from src.matching.matchers import IndexedMatcher, SqlLoopMatcher
    from src.matching.queue import match_document

    subscription = make.subscription()
    document = make.document()
    first = document.fragmentos[0]
    first.embedding = [0.6, 0.8] + [0.0] * 1022
    db_session.add_all(
        Fragmento(documento_id=document.id, posicion=i, texto=f"fragmento {i}", fecha=document.fecha, embedding=vector)
        for i, vector in enumerate(([0.9, 0.1] + [0.0] * 1022, [0.7, 0.7] + [0.0] * 1022), start=1)
    )
    db_session.commit()
    match_document(db_session, document, SqlLoopMatcher() if backend == "loop" else IndexedMatcher(1024))
    match = db_session.query(EvaluacionMatch).one()
    assert match.suscripcion_id == subscription.id and match.fragmento.posicion == 1


def test_a_tie_goes_to_the_first_fragment(db_session, make) -> None:
    from src.db.models import EvaluacionMatch, Fragmento
    from src.matching.matchers import IndexedMatcher, SqlLoopMatcher

    make.subscription()
    document = make.document()
    vector = [0.9, 0.1] + [0.0] * 1022
    document.fragmentos[0].embedding = vector
    db_session.add(Fragmento(documento_id=document.id, posicion=1, texto="copia", fecha=document.fecha, embedding=vector))
    db_session.commit()
    for matcher in (SqlLoopMatcher(), IndexedMatcher(1024)):
        (found,) = matcher.match(db_session, document, 0.5)
        assert found.fragment_id == document.fragmentos[0].id
    assert db_session.query(EvaluacionMatch).count() == 0


def test_a_deleted_fragment_leaves_the_match(db_session, make) -> None:
    match = make.match(make.subscription())
    db_session.delete(match.documento.fragmentos[0])
    db_session.commit()
    db_session.refresh(match)
    assert match.fragmento_id is None
