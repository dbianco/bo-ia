"""Plan 10: deliveries are written with the match and sent apart, with retries."""
import datetime
import random
import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import EntregaNotificacion, EvaluacionMatch
from src.matching.queue import process_queue
from src.notifications import outbox
from src.notifications.outbox import LEASE, send_pending
from src.notifications.worker import NotificationWorker
from tests.matching.conftest import FixedEmbedder
from tests.notifications.conftest import T0, Clock


def _emails(session: Session) -> list[EntregaNotificacion]:
    session.expire_all()
    return list(
        session.scalars(
            select(EntregaNotificacion).where(EntregaNotificacion.canal == "correo").order_by(EntregaNotificacion.id)
        )
    )


def test_a_match_writes_its_deliveries_and_sends_nothing(db_session, make, smtp) -> None:
    match = make.match(make.subscription())
    rows = {e.canal: e for e in match.entregas}
    assert rows["bandeja"].estado == "entregada" and rows["correo"].estado == "pendiente"
    assert smtp.connections == 0


def test_the_delivery_is_in_the_transaction_of_the_match(db_session, make, monkeypatch) -> None:
    """Neither without the other, whenever the process dies."""
    from src.matching import queue

    make.subscription()
    document = make.document()
    document.fragmentos[0].embedding = [1.0] + [0.0] * 1023
    queue.enqueue(db_session, document)
    db_session.commit()

    real = queue.crear_entregas_para_match

    def dies(*args, **kwargs):
        real(*args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(queue, "crear_entregas_para_match", dies)
    from src.matching.matchers import SqlLoopMatcher

    with pytest.raises(KeyboardInterrupt):
        process_queue(db_session, SqlLoopMatcher())
    db_session.rollback()
    assert db_session.query(EvaluacionMatch).count() == db_session.query(EntregaNotificacion).count() == 0


def test_sends_and_records_the_result(db_session, make, smtp, settings, clock) -> None:
    user = make.user("cliente@example.org")
    make.match(make.subscription(user))
    assert send_pending(db_session, settings, clock=clock) == 1
    assert smtp.recipients == ["cliente@example.org"]
    (row,) = _emails(db_session)
    assert row.estado == "entregada" and row.fecha_intento == T0 and row.reintentos == 0 and row.error_proveedor is None
    assert send_pending(db_session, settings, clock=clock) == 0
    assert len(smtp.messages) == 1


def test_with_the_server_down_nothing_is_lost_and_then_all_are_sent(db_session, make, smtp, settings, clock) -> None:
    subscription = make.subscription()
    for _ in range(6):
        make.match(subscription)
    smtp.stop()
    for _ in range(3):
        assert send_pending(db_session, settings, clock=clock) == 0
        clock.advance(minutes=30)
    assert {e.estado for e in _emails(db_session)} == {"pendiente"}
    smtp.start()
    clock.advance(hours=2)
    while send_pending(db_session, settings, clock=clock):
        clock.advance(hours=2)
    assert {e.estado for e in _emails(db_session)} == {"entregada"}
    assert len(smtp.messages) == 6


def test_a_server_that_is_down_is_not_asked_for_each_email(db_session, make, smtp, settings, clock) -> None:
    """A connection that times out takes ten seconds."""
    subscription = make.subscription()
    for _ in range(10):
        make.match(subscription)
    smtp.replies["CONNECT"] = "421 try later"
    send_pending(db_session, settings, clock=clock)
    assert smtp.connections == 1
    assert sum(e.fecha_intento is not None for e in _emails(db_session)) == 1, "the others have not failed"


def test_waits_longer_after_each_failure_up_to_a_limit_and_then_gives_up(db_session, make, smtp, settings, clock) -> None:
    make.match(make.subscription())
    smtp.replies["MAIL"] = "451 later"
    waits = []
    for attempt in range(settings.max_retries + 1):
        send_pending(db_session, settings, clock=clock)
        (row,) = _emails(db_session)
        assert row.reintentos == attempt
        if row.estado == "fallida":
            break
        waits.append((row.next_attempt_at - clock.now).total_seconds())
        clock.now = row.next_attempt_at - datetime.timedelta(seconds=1)
        assert send_pending(db_session, settings, clock=clock) == 0
        assert _emails(db_session)[0].reintentos == attempt, "not before its time"
        clock.now = row.next_attempt_at
    assert row.estado == "fallida" and "451" in row.error_proveedor and row.reintentos == settings.max_retries
    assert waits == sorted(waits) and waits[0] < waits[1] < waits[2] and max(waits) <= 3600


@pytest.mark.parametrize(
    "fail",
    [
        lambda s: s.reject.update({"bad@example.org": "550 no such user"}),
        lambda s: s.replies.update({"END": "554 rejected as spam"}),
    ],
    ids=["rejected address", "rejected content"],
)
def test_a_permanent_failure_is_not_retried(db_session, make, smtp, settings, clock, fail) -> None:
    make.match(make.subscription(make.user("bad@example.org")))
    make.match(make.subscription(make.user("good@example.org")))
    fail(smtp)
    send_pending(db_session, settings, clock=clock)
    row = _emails(db_session)[0]
    assert row.estado == "fallida" and row.error_proveedor
    clock.advance(days=1)
    send_pending(db_session, settings, clock=clock)
    assert _emails(db_session)[0].reintentos == 0


@pytest.mark.parametrize(
    "reply", [("MAIL", "550 sender not allowed"), ("MAIL", "451 later"), ("RCPT", "450 mailbox busy"), ("END", "452 full")]
)
def test_a_failure_that_may_pass_is_retried(db_session, make, smtp, settings, clock, reply) -> None:
    """A refused sender is a mistake in the configuration: no email is lost while it is fixed."""
    make.match(make.subscription())
    smtp.replies[reply[0]] = reply[1]
    send_pending(db_session, settings, clock=clock)
    assert _emails(db_session)[0].estado == "pendiente"
    smtp.replies.clear()
    clock.advance(hours=2)
    assert send_pending(db_session, settings, clock=clock) == 1


def test_without_a_mail_server_the_channel_fails_at_once(db_session, make, settings, clock, monkeypatch) -> None:
    monkeypatch.delenv("SMTP_HOST", raising=False)
    make.match(make.subscription())
    send_pending(db_session, settings, clock=clock)
    (row,) = _emails(db_session)
    assert row.estado == "fallida" and "SMTP_HOST" in row.error_proveedor


@pytest.mark.parametrize("address", ["sin-arroba", "a@example.org\nBcc: x@example.org", "ñandú@example.org"])
def test_an_address_that_cannot_be_used_does_not_stop_the_others(db_session, make, smtp, settings, clock, address) -> None:
    make.match(make.subscription(make.user(address)))
    make.match(make.subscription(make.user("good@example.org")))
    smtp.reject["sin-arroba"] = "501 bad address"
    send_pending(db_session, settings, clock=clock)
    assert [e.estado for e in _emails(db_session)] == ["fallida", "entregada"]
    assert smtp.recipients[-1] == "good@example.org" and "x@example.org" not in smtp.recipients


def test_an_unexpected_error_is_retried_and_does_not_stop_the_others(db_session, make, smtp, settings, clock, monkeypatch) -> None:
    make.match(make.subscription())
    make.match(make.subscription())
    real, calls = outbox.render_alert, []

    def breaks(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("bug")
        return real(*args, **kwargs)

    monkeypatch.setattr(outbox, "render_alert", breaks)
    assert send_pending(db_session, settings, clock=clock) == 1
    assert [e.estado for e in _emails(db_session)] == ["pendiente", "entregada"]


def test_the_message_identifier_is_stable_and_unique(db_session, make, smtp, settings, clock) -> None:
    subscription = make.subscription()
    make.match(subscription)
    smtp.drop_after_accepting = True  # accepted, and the connection dies before the answer
    send_pending(db_session, settings, clock=clock)
    smtp.drop_after_accepting = False
    make.match(subscription)
    clock.advance(hours=2)
    send_pending(db_session, settings, clock=clock)
    identifiers = [m["Message-ID"] for m in smtp.messages]
    assert len(identifiers) == 3 and len(set(identifiers)) == 2, "the repeated email has the same one"
    assert all(i.startswith("<") and i.endswith("@contextcrawl.local>") for i in identifiers)


def test_the_identifiers_of_two_installations_differ(db_session, make, smtp, settings, clock) -> None:
    import dataclasses

    make.match(make.subscription())
    (row,) = _emails(db_session)
    other = dataclasses.replace(settings, installation="Otra")
    assert outbox.message_id(settings, "alert", [row.id], T0) != outbox.message_id(other, "alert", [row.id], T0)


# --- several workers, and workers that die ---


def test_two_workers_do_not_take_the_same_row(db_session, make, smtp, settings, clock, monkeypatch) -> None:
    make.match(make.subscription())
    other = sessionmaker(bind=db_session.get_bind())()
    real, nested = outbox.enviar_correo, []

    def send(**mail):
        nested.append(send_pending(other, settings, clock=clock))  # another worker, at this moment
        return real(**mail)

    monkeypatch.setattr(outbox, "enviar_correo", send)
    assert send_pending(db_session, settings, clock=clock) == 1
    assert nested == [0] and len(smtp.messages) == 1
    other.close()


def test_many_workers_at_once_send_each_email_once(db_session, make, smtp, settings, clock) -> None:
    import threading

    subscription = make.subscription()
    for _ in range(25):
        make.match(subscription)
    sessions, barrier, sent = sessionmaker(bind=db_session.get_bind()), threading.Barrier(5, timeout=10), []

    def work() -> None:
        with sessions() as session:
            barrier.wait()
            sent.append(send_pending(session, settings, clock=clock))

    threads = [threading.Thread(target=work) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert sum(sent) == len(smtp.messages) == len({m["Message-ID"] for m in smtp.messages}) == 25


def test_a_row_that_another_worker_is_claiming_is_skipped(db_session, make, smtp, settings, clock) -> None:
    """It does not wait for it, and it does not take it."""
    first, second = make.match(make.subscription()), make.match(make.subscription())
    ids = [e.id for m in (first, second) for e in m.entregas if e.canal == "correo"]
    other = sessionmaker(bind=db_session.get_bind())()
    other.get(EntregaNotificacion, ids[0], with_for_update=True)
    assert send_pending(db_session, settings, clock=clock, limit=1) == 1
    other.rollback()
    other.close()
    assert {e.id: e.estado for e in _emails(db_session)} == {ids[0]: "pendiente", ids[1]: "entregada"}


class Killed(BaseException):
    pass


POINTS = ("claimed", "before sending", "after sending", "recorded")


def _kill_at(point: str, monkeypatch, session: Session) -> None:
    if point == "claimed":
        monkeypatch.setattr(outbox, "render_alert", lambda *a, **k: (_ for _ in ()).throw(Killed()))
    elif point in ("before sending", "after sending"):
        real = outbox.enviar_correo

        def send(**mail):
            if point == "after sending":
                real(**mail)
            raise Killed

        monkeypatch.setattr(outbox, "enviar_correo", send)
    else:
        real_record = outbox._record_sent

        def record(*args):
            real_record(*args)
            session.commit()
            raise Killed

        monkeypatch.setattr(outbox, "_record_sent", record)


@pytest.mark.parametrize("point", POINTS)
def test_a_worker_that_dies_loses_nothing(db_session, make, smtp, settings, clock, monkeypatch, point) -> None:
    make.match(make.subscription())
    with monkeypatch.context() as patch:
        _kill_at(point, patch, db_session)
        with pytest.raises(Killed):
            send_pending(db_session, settings, clock=clock)
        db_session.rollback()
    assert send_pending(db_session, settings, clock=clock) == 0, "still claimed, or already sent"
    clock.now += LEASE + datetime.timedelta(seconds=1)
    send_pending(db_session, settings, clock=clock)
    assert _emails(db_session)[0].estado == "entregada"
    # The only window for a duplicate: between the server accepting it and recording it.
    assert len(smtp.messages) == (2 if point == "after sending" else 1)


@pytest.mark.parametrize("seed", range(6))
def test_random_deaths_send_everything_at_least_once(db_session, make, smtp, settings, clock, monkeypatch, seed) -> None:
    rng = random.Random(seed)
    subscription = make.subscription()
    for _ in range(8):
        make.match(subscription)
    windows = 0
    for _ in range(60):
        point = rng.choice((*POINTS, None, None))
        with monkeypatch.context() as patch:
            if point:
                _kill_at(point, patch, db_session)
            before = len(smtp.messages)
            try:
                send_pending(db_session, settings, clock=clock)
            except Killed:
                db_session.rollback()
                windows += point == "after sending" and len(smtp.messages) > before
        clock.now += LEASE + datetime.timedelta(seconds=rng.randrange(0, 600))
    assert {e.estado for e in _emails(db_session)} == {"entregada"}
    assert len({m["Message-ID"] for m in smtp.messages}) == 8
    assert len(smtp.messages) == 8 + windows


def test_a_message_that_kills_its_worker_each_time_is_given_up(db_session, make, smtp, settings, clock, monkeypatch) -> None:
    make.match(make.subscription())
    with monkeypatch.context() as patch:
        _kill_at("before sending", patch, db_session)
        for _ in range(settings.max_retries + 3):
            try:
                send_pending(db_session, settings, clock=clock)
            except Killed:
                db_session.rollback()
            clock.now += LEASE + datetime.timedelta(hours=2)
    assert _emails(db_session)[0].estado == "fallida"


# --- the whole path ---


def test_ingestion_takes_the_same_with_the_mail_server_down(db_session, make, monkeypatch) -> None:
    from src.ingestor.contract import DocumentoNormalizado, ingerir_documento
    from src.matching.matchers import IndexedMatcher

    make.subscription()
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", "1")

    def fails(*args, **kwargs):
        raise AssertionError("a connection was attempted")

    monkeypatch.setattr("smtplib.SMTP", fails)
    document = DocumentoNormalizado("f", "x", datetime.date(2026, 1, 1), "texto", "https://example.org")
    ingerir_documento(db_session, FixedEmbedder(), document)
    process_queue(db_session, IndexedMatcher(1024))
    assert [e.estado for e in _emails(db_session)] == ["pendiente"]


def _wait(condition, seconds=10) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_the_worker_sends_in_the_background_and_survives_errors(db_session, make, smtp, settings, monkeypatch) -> None:
    from src.notifications import worker as module

    real, calls = module.send_pending, []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("connection lost")
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "send_pending", flaky)
    now = datetime.datetime.now(datetime.UTC)
    make.match(make.subscription(), at=now)
    worker = NotificationWorker(db_session.get_bind(), settings, poll_seconds=0.05)
    worker.start()
    try:
        assert _wait(lambda: len(smtp.messages) == 1)
        make.match(make.subscription(), at=now)
        assert _wait(lambda: len(smtp.messages) == 2)
    finally:
        worker.stop()
    assert not worker.is_alive()


def test_the_service_runs_the_worker(db_session, make, smtp, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from src.api import main
    from src.config.installation import InstallationConfig

    monkeypatch.setattr(main, "get_installation_config", lambda: InstallationConfig(nombre="x", seed=False))
    monkeypatch.setattr(main.deps, "_engine", lambda: db_session.get_bind())
    monkeypatch.setattr(main, "get_embedder", lambda: None)
    monkeypatch.setenv("NOTIFICATIONS_POLL_SECONDS", "0.05")
    make.match(make.subscription(), at=datetime.datetime.now(datetime.UTC))
    with TestClient(main.app):
        assert _wait(lambda: len(smtp.messages) == 1)


def test_the_default_clock_is_the_one_of_the_database(db_session) -> None:
    now = outbox.database_clock(db_session)
    assert abs(now - datetime.datetime.now(datetime.UTC)) < datetime.timedelta(minutes=5)
    assert Clock()(db_session) == T0
