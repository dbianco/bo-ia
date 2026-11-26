"""Plan 10: daily and weekly digests."""
import datetime
import random
from collections import Counter
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Digest, EntregaNotificacion
from src.notifications import outbox
from src.notifications.digests import build_digests, last_boundary
from src.notifications.outbox import LEASE, send_pending
from tests.notifications.conftest import T0

CORDOBA = ZoneInfo("America/Argentina/Cordoba")  # UTC-3 all year
HOUR = datetime.timedelta(hours=1)
DAY = datetime.timedelta(days=1)


def local(*args, zone=CORDOBA) -> datetime.datetime:
    return datetime.datetime(*args, tzinfo=zone).astimezone(datetime.UTC)


@pytest.mark.parametrize(
    ("now", "frequency", "expected"),
    [
        (local(2026, 6, 3, 12), "daily", local(2026, 6, 3, 7)),
        (local(2026, 6, 3, 7), "daily", local(2026, 6, 3, 7)),
        (local(2026, 6, 3, 6, 59), "daily", local(2026, 6, 2, 7)),
        (local(2026, 6, 3, 23, 30), "daily", local(2026, 6, 3, 7)),  # already the next day in UTC
        (local(2026, 6, 3, 12), "weekly", local(2026, 6, 1, 7)),
        (local(2026, 6, 1, 7), "weekly", local(2026, 6, 1, 7)),
        (local(2026, 6, 1, 6), "weekly", local(2026, 5, 25, 7)),
        (local(2026, 6, 7, 23, 59), "weekly", local(2026, 6, 1, 7)),
    ],
)
def test_periods_use_the_time_zone_of_the_installation(now, frequency, expected) -> None:
    assert last_boundary(now, frequency, CORDOBA, 7) == expected


def test_periods_across_a_change_of_the_clock() -> None:
    madrid = ZoneInfo("Europe/Madrid")  # summer time begins on 2026-03-29
    before = last_boundary(local(2026, 3, 28, 12, zone=madrid), "daily", madrid, 7)
    after = last_boundary(local(2026, 3, 29, 12, zone=madrid), "daily", madrid, 7)
    assert after - before == 23 * HOUR


def _emails(session: Session) -> list[EntregaNotificacion]:
    session.expire_all()
    return list(session.scalars(select(EntregaNotificacion).where(EntregaNotificacion.canal == "correo")))


def _run(session, settings, clock) -> int:
    build_digests(session, settings, clock=clock)
    return send_pending(session, settings, clock=clock)


def test_matches_wait_for_the_digest_and_are_in_one_email(db_session, make, smtp, settings, clock) -> None:
    user = make.user("cliente@example.org")
    a = make.subscription(user, "pavimentación de calles", frequency="daily")
    b = make.subscription(user, "puentes", frequency="daily")
    for subscription, title in ((a, "Uno"), (a, "Dos"), (b, "Tres")):
        make.match(subscription, make.document(titulo=title))
    assert _run(db_session, settings, clock) == 0 and smtp.messages == []
    clock.now = local(2026, 6, 4, 7, 1)
    assert _run(db_session, settings, clock) == 1
    assert smtp.recipients == ["cliente@example.org"]
    text = smtp.text()
    assert all(text.count(t) == 1 for t in ("Uno", "Dos", "Tres"))
    assert text.index("puentes") > 0 and text.count("pavimentación de calles") >= 1
    assert {e.estado for e in _emails(db_session)} == {"entregada"}


def test_running_it_twice_sends_it_once(db_session, make, smtp, settings, clock) -> None:
    make.match(make.subscription(frequency="daily"))
    clock.now = local(2026, 6, 4, 8)
    for _ in range(3):
        _run(db_session, settings, clock)
    clock.advance(hours=3)
    _run(db_session, settings, clock)
    assert len(smtp.messages) == 1 and db_session.query(Digest).count() == 1


def test_an_empty_period_sends_nothing(db_session, make, smtp, settings, clock) -> None:
    make.subscription(frequency="daily")
    for _ in range(5):
        clock.advance(days=1)
        _run(db_session, settings, clock)
    assert smtp.messages == [] and db_session.query(Digest).count() == 0


def test_each_user_has_a_digest_and_frequencies_are_apart(db_session, make, smtp, settings, clock) -> None:
    one, two = make.user("one@example.org"), make.user("two@example.org")
    for user, frequency in ((one, "daily"), (one, "weekly"), (two, "daily"), (one, "immediate")):
        make.match(make.subscription(user, frequency=frequency))
    assert _run(db_session, settings, clock) == 1, "the immediate one"
    clock.now = local(2026, 6, 4, 8)
    _run(db_session, settings, clock)
    assert Counter(smtp.recipients) == {"one@example.org": 2, "two@example.org": 1}
    clock.now = local(2026, 6, 8, 8)  # Monday
    _run(db_session, settings, clock)
    assert Counter(smtp.recipients) == {"one@example.org": 3, "two@example.org": 1}


def test_the_inbox_does_not_wait_for_the_digest(db_session, make) -> None:
    match = make.match(make.subscription(frequency="weekly"))
    assert {e.canal: e.estado for e in match.entregas} == {"bandeja": "entregada", "correo": "pendiente"}


def test_after_days_without_running_there_is_one_digest_with_everything(db_session, make, smtp, settings, clock) -> None:
    subscription = make.subscription(frequency="daily")
    for i in range(4):
        make.match(subscription, make.document(titulo=f"Día {i}"), at=T0 + i * DAY)
    clock.now = local(2026, 6, 9, 8)
    _run(db_session, settings, clock)
    assert len(smtp.messages) == 1 and all(f"Día {i}" in smtp.text() for i in range(4))


def test_a_match_of_the_period_committed_after_the_digest_is_in_the_next(db_session, make, smtp, settings, clock) -> None:
    """Its transaction began before the end of the period and finished after it."""
    subscription = make.subscription(frequency="daily")
    make.match(subscription, make.document(titulo="A tiempo"))
    clock.now = local(2026, 6, 4, 7, 0)
    _run(db_session, settings, clock)
    make.match(subscription, make.document(titulo="Tarde"), at=local(2026, 6, 4, 6, 59))
    _run(db_session, settings, clock)
    assert len(smtp.messages) == 1 and "Tarde" not in smtp.text()
    clock.advance(days=1)
    _run(db_session, settings, clock)
    assert len(smtp.messages) == 2 and "Tarde" in smtp.text() and "A tiempo" not in smtp.text()


def test_a_match_that_arrives_while_the_digest_is_built(db_session, make, smtp, settings, clock) -> None:
    """In another transaction, not committed yet."""
    subscription = make.subscription(frequency="daily")
    first = make.match(subscription, make.document(titulo="Primero"))
    document = make.document(titulo="Segundo")
    match_id, document_id = first.id, document.id
    other = sessionmaker(bind=db_session.get_bind())()
    from src.db.models import EvaluacionMatch
    from src.notifications.dispatcher import crear_entregas_para_match

    pending = EvaluacionMatch(
        documento_id=document_id, suscripcion_id=subscription.id, score=0.9, filtros_aplicados={},
        fecha_evaluacion=T0,
    )  # fmt: skip
    other.add(pending)
    other.flush()
    crear_entregas_para_match(other, pending, now=T0)
    other.flush()
    clock.now = local(2026, 6, 4, 7, 30)
    _run(db_session, settings, clock)
    other.commit()
    other.close()
    _run(db_session, settings, clock)
    clock.advance(days=1)
    _run(db_session, settings, clock)
    assert ["Primero" in smtp.text(i) for i in range(2)] == [True, False]
    assert ["Segundo" in smtp.text(i) for i in range(2)] == [False, True]
    assert match_id


def test_a_digest_does_not_take_what_is_in_another(db_session, make, smtp, settings, clock) -> None:
    """The first is still trying, and might be sending it at this moment."""
    subscription = make.subscription(frequency="daily")
    make.match(subscription, make.document(titulo="Primero"))
    smtp.replies["MAIL"] = "451 later"
    clock.now = local(2026, 6, 4, 8)
    _run(db_session, settings, clock)
    (row,) = _emails(db_session)
    first = row.digest_id
    clock.advance(days=1)
    assert build_digests(db_session, settings, clock=clock) == 0
    assert _emails(db_session)[0].digest_id == first is not None
    make.match(subscription, make.document(titulo="Segundo"), at=clock.now)
    clock.advance(days=1)
    assert build_digests(db_session, settings, clock=clock) == 1
    assert len({e.digest_id for e in _emails(db_session)}) == 2


def test_two_workers_build_one_digest(db_session, make, settings, clock) -> None:
    import threading

    user = make.user()
    for _ in range(20):
        make.match(make.subscription(user, frequency="daily"))
    clock.now = local(2026, 6, 4, 8)
    db_session.commit()
    sessions, barrier = sessionmaker(bind=db_session.get_bind()), threading.Barrier(4, timeout=10)

    def build() -> None:
        with sessions() as session:
            barrier.wait()
            build_digests(session, settings, clock=clock)

    threads = [threading.Thread(target=build) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert db_session.query(Digest).count() == 1
    assert all(e.digest_id is not None for e in _emails(db_session))


@pytest.mark.parametrize("seed", range(8))
def test_each_match_is_in_exactly_one_digest(db_session, make, smtp, settings, clock, seed) -> None:
    """A long random sequence of matches, digest runs, failures of the server and deaths of the worker."""
    rng = random.Random(seed)
    users = [make.user() for _ in range(2)]
    subscriptions = [make.subscription(u, f"tema {i}", frequency=f)
                     for u in users for i, f in enumerate(("daily", "daily", "weekly"))]  # fmt: skip
    titles = []
    for step in range(60):
        action = rng.random()
        if action < 0.55:
            title = f"T{step:03d}T"
            titles.append(title)
            # Sometimes it was evaluated a little before it is committed.
            make.match(rng.choice(subscriptions), make.document(titulo=title), at=clock.now - rng.randrange(3) * HOUR)
        elif action < 0.9:
            smtp.replies = {"MAIL": "451 later"} if rng.random() < 0.3 else {}
            _run(db_session, settings, clock)
        clock.now += rng.randrange(1, 15) * HOUR
    smtp.replies = {}
    for _ in range(12):
        clock.now += 2 * DAY
        _run(db_session, settings, clock)
    seen = Counter(t for m in range(len(smtp.messages)) for t in titles if t in smtp.text(m))
    assert seen == Counter({t: 1 for t in titles})
    assert {e.estado for e in _emails(db_session)} == {"entregada"}


@pytest.mark.parametrize("point", ["before sending", "after sending"])
def test_a_worker_that_dies_sending_a_digest(db_session, make, smtp, settings, clock, monkeypatch, point) -> None:
    class Killed(BaseException):
        pass

    make.match(make.subscription(frequency="daily"))
    clock.now = local(2026, 6, 4, 8)
    real = outbox.enviar_correo

    def send(**mail):
        if point == "after sending":
            real(**mail)
        raise Killed

    with monkeypatch.context() as patch:
        patch.setattr(outbox, "enviar_correo", send)
        with pytest.raises(Killed):
            _run(db_session, settings, clock)
        db_session.rollback()
    _run(db_session, settings, clock)
    clock.now += LEASE + datetime.timedelta(seconds=1)
    _run(db_session, settings, clock)
    assert {e.estado for e in _emails(db_session)} == {"entregada"}
    assert len({m["Message-ID"] for m in smtp.messages}) == 1
    assert len(smtp.messages) == (2 if point == "after sending" else 1)


def test_a_digest_that_fails_for_good(db_session, make, smtp, settings, clock) -> None:
    make.match(make.subscription(make.user("bad@example.org"), frequency="daily"))
    smtp.reject["bad@example.org"] = "550 no such user"
    clock.now = local(2026, 6, 4, 8)
    _run(db_session, settings, clock)
    assert {e.estado for e in _emails(db_session)} == {"fallida"}
    assert db_session.query(Digest).one().estado == "fallida"


def test_matches_are_ordered_by_score_and_all_of_them_appear(db_session, make, smtp, settings, clock) -> None:
    subscription = make.subscription(frequency="daily")
    for i in range(45):
        make.match(subscription, make.document(titulo=f"T{i:03d}T"), score=0.5 + i / 100)
    clock.now = local(2026, 6, 4, 8)
    _run(db_session, settings, clock)
    for body in (smtp.text(), smtp.html()):
        at = [body.index(f"T{i:03d}T") for i in range(45)]
        assert at == sorted(at, reverse=True)
    assert smtp.text().count("Licitación para la pavimentación") < 45, "only the first ones have an excerpt"


def test_changing_the_frequency_leaves_what_was_already_waiting(db_session, make, smtp, settings, clock) -> None:
    subscription = make.subscription(frequency="daily")
    make.match(subscription, make.document(titulo="Antes"))
    subscription.frecuencia_notificacion = "immediate"
    db_session.commit()
    make.match(subscription, make.document(titulo="Después"))
    assert _run(db_session, settings, clock) == 1 and "Después" in smtp.text()
    clock.now = local(2026, 6, 4, 8)
    assert _run(db_session, settings, clock) == 1 and "Antes" in smtp.text()


def test_a_deleted_subscription_disappears_from_the_digest(db_session, make, smtp, settings, clock) -> None:
    user = make.user()
    gone = make.subscription(user, frequency="daily")
    make.match(gone, make.document(titulo="Borrada"))
    make.match(make.subscription(user, frequency="daily"), make.document(titulo="Queda"))
    db_session.delete(gone)
    db_session.commit()
    clock.now = local(2026, 6, 4, 8)
    _run(db_session, settings, clock)
    assert "Queda" in smtp.text() and "Borrada" not in smtp.text()


def test_a_digest_left_without_matches_is_not_sent(db_session, make, smtp, settings, clock) -> None:
    subscription = make.subscription(frequency="daily")
    make.match(subscription)
    clock.now = local(2026, 6, 4, 8)
    build_digests(db_session, settings, clock=clock)
    db_session.delete(subscription)
    db_session.commit()
    send_pending(db_session, settings, clock=clock)
    assert smtp.messages == []
    assert db_session.query(Digest).filter_by(estado="pendiente").count() == 0
