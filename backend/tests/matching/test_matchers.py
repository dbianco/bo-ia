"""Plan 3: the two implementations behind one interface, on the database."""
import random

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Suscripcion
from src.matching.matchers import IndexedMatcher, SqlLoopMatcher, matcher_from_environment
from tests.matching.conftest import axis

CORDOBA = {"provincia": {"tipo": "seleccion", "valor": "Córdoba"}}


@pytest.fixture(params=["loop", "indexed"])
def matcher(request):
    return SqlLoopMatcher() if request.param == "loop" else IndexedMatcher(axis(1.0).__len__())


def _ids(matcher, session, document, threshold=0.5) -> dict[int, float]:
    return {f.subscription_id: round(f.score, 4) for f in matcher.match(session, document, threshold)}


def test_matches_by_meaning_and_filters(db_session: Session, matcher, subscribe, ingest) -> None:
    near, far = subscribe(axis(0.8)), subscribe(axis(0.0, 1.0))
    filtered, other = subscribe(axis(0.6), CORDOBA), subscribe(axis(0.6), {"provincia": {"tipo": "seleccion", "valor": "X"}})
    document = ingest(metadata={"provincia": "Córdoba"})
    assert _ids(matcher, db_session, document) == {near.id: 0.8, filtered.id: 0.6}
    assert far.id and other.id


def test_only_active_subscriptions(db_session: Session, matcher, subscribe, ingest) -> None:
    subscription = subscribe()
    document = ingest()
    assert _ids(matcher, db_session, document) == {subscription.id: 1.0}
    for state, expected in (("pausada", {}), ("activa", {subscription.id: 1.0})):
        subscription.estado = state
        db_session.commit()
        assert _ids(matcher, db_session, document) == expected


def test_created_changed_and_deleted_subscriptions_are_seen(db_session: Session, matcher, subscribe, ingest) -> None:
    document = ingest()
    assert _ids(matcher, db_session, document) == {}
    first, second = subscribe(axis(0.9)), subscribe(axis(0.7))
    assert _ids(matcher, db_session, document) == {first.id: 0.9, second.id: 0.7}
    first.embedding = axis(0.6)
    second.filtros = CORDOBA
    db_session.commit()
    assert _ids(matcher, db_session, document) == {first.id: 0.6}
    db_session.delete(first)
    db_session.commit()
    assert _ids(matcher, db_session, document) == {}


def test_the_best_fragment_counts(db_session: Session, matcher, subscribe, ingest) -> None:
    subscription = subscribe()
    document = ingest("v:0.2 " + "a" * 1200)
    for fragment, weight in zip(document.fragmentos, (0.55, 0.9), strict=True):
        fragment.embedding = axis(weight)
    db_session.commit()
    assert _ids(matcher, db_session, document) == {subscription.id: 0.9}


def test_vectors_that_are_not_normalized(db_session: Session, matcher, subscribe, ingest) -> None:
    subscription = subscribe([3 * x for x in axis(0.8)])
    assert _ids(matcher, db_session, ingest()) == {subscription.id: 0.8}


def test_random_histories_give_the_same_matches(db_session: Session, subscribe, ingest, user) -> None:
    rng = random.Random(5)
    loop, indexed = SqlLoopMatcher(), IndexedMatcher(1024)
    alive: list[Suscripcion] = []
    for _ in range(12):
        for _ in range(6):
            action = rng.choice(["add", "add", "pause", "resume", "delete"])
            if action == "add" or not alive:
                filters = rng.choice([{}, CORDOBA, {"monto": {"tipo": "rango_numerico", "valor": "10,20"}}])
                alive.append(subscribe(axis(rng.random() * 0.7, rng.random() * 0.7), filters))
            elif action == "delete":
                db_session.delete(alive.pop(rng.randrange(len(alive))))
            else:
                rng.choice(alive).estado = "pausada" if action == "pause" else "activa"
            db_session.commit()
        document = ingest(
            f"v:{rng.random() * 0.7:.3f},{rng.random() * 0.7:.3f}",
            {"provincia": rng.choice(["Córdoba", "X"]), "monto": rng.randrange(30)},
        )
        assert _ids(indexed, db_session, document) == _ids(loop, db_session, document)


def test_a_change_committed_late_is_not_missed(db_session: Session, test_database_url, subscribe, ingest) -> None:
    """A transaction that starts before another may commit after it: its change
    is older than the ones already seen."""
    matcher = IndexedMatcher(1024)
    document = ingest()
    paused = subscribe(estado="pausada")
    other = sessionmaker(bind=db_session.get_bind())()
    try:
        other.get(Suscripcion, paused.id).estado = "activa"
        other.flush()  # its transaction has started, and is not committed
        newer = subscribe(axis(0.9))
        assert _ids(matcher, db_session, document) == {newer.id: 0.9}
        db_session.commit()
        other.commit()
        assert _ids(matcher, db_session, document) == {newer.id: 0.9, paused.id: 1.0}
    finally:
        other.close()


def test_an_index_reads_only_what_changed(db_session: Session, subscribe, ingest) -> None:
    matcher = IndexedMatcher(1024)
    for _ in range(5):
        subscribe()
    document = ingest()
    assert matcher.sync(db_session) == 5
    db_session.commit()
    matcher.sync(db_session)  # the boundary may be read twice
    db_session.execute(text("SELECT pg_current_xact_id()"))
    db_session.commit()
    assert matcher.sync(db_session) == 0
    subscribe()
    assert 1 <= matcher.sync(db_session) <= 2
    assert len(_ids(matcher, db_session, document)) == 6


def test_selection_by_setting(monkeypatch) -> None:
    monkeypatch.delenv("MATCHING_ENGINE", raising=False)
    assert isinstance(matcher_from_environment(), IndexedMatcher)
    monkeypatch.setenv("MATCHING_ENGINE", "loop")
    assert isinstance(matcher_from_environment(), SqlLoopMatcher)
    monkeypatch.setenv("MATCHING_ENGINE", "magic")
    with pytest.raises(ValueError, match="magic"):
        matcher_from_environment()
