"""Plan 3: matching after ingestion, outside its transaction."""
import datetime
import time

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from src.db.models import EntregaNotificacion, EvaluacionMatch, MatchingQueue
from src.ingestor.contract import DocumentoNormalizado, ErrorDeProcesamiento, ingerir_documento
from src.matching.matchers import IndexedMatcher, SqlLoopMatcher
from src.matching.queue import process_queue
from src.matching.worker import MatchingWorker
from src.notifications import dispatcher
from tests.matching.conftest import axis


@pytest.fixture(params=["loop", "indexed"])
def matcher(request):
    return SqlLoopMatcher() if request.param == "loop" else IndexedMatcher(1024)


def _matches(session: Session) -> list[EvaluacionMatch]:
    session.expire_all()
    return list(session.scalars(select(EvaluacionMatch).order_by(EvaluacionMatch.id)))


def _queued(session: Session) -> list[MatchingQueue]:
    session.expire_all()
    return list(session.scalars(select(MatchingQueue).order_by(MatchingQueue.documento_id)))


def test_ingestion_only_queues_the_document(db_session: Session, subscribe, ingest) -> None:
    subscribe()
    document = ingest()
    assert document.estado == "completo"
    assert _matches(db_session) == []
    assert [q.documento_id for q in _queued(db_session)] == [document.id]


def test_the_queue_records_the_same_as_before(db_session: Session, matcher, subscribe, ingest) -> None:
    subscription = subscribe(axis(0.8), {"a": {"tipo": "seleccion", "valor": "x"}})
    document = ingest(metadata={"a": "x"})
    assert process_queue(db_session, matcher) == 1
    (match,) = _matches(db_session)
    assert (match.documento_id, match.suscripcion_id, match.score) == (document.id, subscription.id, 0.8)
    assert match.filtros_aplicados == subscription.filtros
    assert match.fecha_evaluacion is not None
    (delivery,) = db_session.scalars(select(EntregaNotificacion)).all()
    assert (delivery.match_id, delivery.canal, delivery.estado) == (match.id, "bandeja", "entregada")
    assert _queued(db_session) == []
    assert process_queue(db_session, matcher) == 0


def test_a_document_is_queued_once_and_only_if_it_is_new_and_complete(db_session: Session, embedder, subscribe) -> None:
    subscribe()
    document = DocumentoNormalizado("f", "d", datetime.date(2026, 1, 1), "texto", "https://example.org")
    ingerir_documento(db_session, embedder, document)
    ingerir_documento(db_session, embedder, document)
    assert len(_queued(db_session)) == 1

    class Fails:
        def embed_passage(self, text):
            raise RuntimeError("no model")

    with pytest.raises(ErrorDeProcesamiento):
        ingerir_documento(
            db_session, Fails(), DocumentoNormalizado("f", "e", datetime.date(2026, 1, 1), "otro", "https://example.org")
        )
    assert len(_queued(db_session)) == 1


def test_without_alerts_nothing_is_queued(db_session: Session, ingest) -> None:
    ingest(evaluate=False)
    assert _queued(db_session) == []


def test_processing_a_document_again_duplicates_nothing(db_session: Session, matcher, subscribe, ingest) -> None:
    subscribe()
    document = ingest()
    process_queue(db_session, matcher)
    db_session.add(MatchingQueue(documento_id=document.id))
    db_session.commit()
    process_queue(db_session, matcher)
    assert len(_matches(db_session)) == 1
    assert len(db_session.scalars(select(EntregaNotificacion)).all()) == 1


def test_a_match_left_without_deliveries_by_a_crash_gets_them(db_session: Session, matcher, subscribe, ingest) -> None:
    subscription, document = subscribe(), ingest()
    db_session.add(
        EvaluacionMatch(
            documento_id=document.id, suscripcion_id=subscription.id, score=1.0,
            fecha_evaluacion=datetime.datetime.now(datetime.UTC),
        )
    )  # fmt: skip
    db_session.commit()
    process_queue(db_session, matcher)
    assert len(_matches(db_session)) == 1
    assert len(db_session.scalars(select(EntregaNotificacion)).all()) == 1


class _FailsOn:
    def __init__(self, document_id: int, times: int = 10**6) -> None:
        self._inner, self._document_id, self._times = SqlLoopMatcher(), document_id, times

    def match(self, session, document, threshold):
        if document.id == self._document_id and self._times > 0:
            self._times -= 1
            raise RuntimeError("cannot match this one")
        return self._inner.match(session, document, threshold)


def test_a_failure_does_not_stop_the_others_and_is_retried_later(db_session: Session, subscribe, ingest) -> None:
    subscribe()
    bad, good = ingest(), ingest()
    matcher = _FailsOn(bad.id, times=1)
    assert process_queue(db_session, matcher) == 1
    assert [m.documento_id for m in _matches(db_session)] == [good.id]
    (left,) = _queued(db_session)
    assert left.documento_id == bad.id and left.attempts == 1 and "cannot match this one" in left.last_error
    assert process_queue(db_session, matcher) == 0, "not before its time"
    db_session.execute(update(MatchingQueue).values(next_attempt_at=text("now() - interval '1 second'")))
    db_session.commit()
    assert process_queue(db_session, matcher) == 1
    assert [m.documento_id for m in _matches(db_session)] == [good.id, bad.id]


def test_waits_longer_after_each_failure_up_to_a_limit(db_session: Session, ingest) -> None:
    document = ingest()
    matcher, waits = _FailsOn(document.id), []
    for _ in range(12):
        process_queue(db_session, matcher)
        waits.append(
            db_session.scalar(text("SELECT extract(epoch FROM next_attempt_at - clock_timestamp()) FROM matching_queue"))
        )
        db_session.execute(update(MatchingQueue).values(next_attempt_at=text("now() - interval '1 second'")))
        db_session.commit()
    assert waits[0] < waits[1] < waits[2]
    assert float(waits[-1]) <= 3600


def test_a_document_claimed_by_another_worker_is_left_to_it(db_session: Session, matcher, subscribe, ingest) -> None:
    subscribe()
    ingest()
    seen = []

    class Nested:
        def match(self, session, document, threshold):
            seen.append(process_queue(session, SqlLoopMatcher()))  # another worker, at this moment
            return matcher.match(session, document, threshold)

    assert process_queue(db_session, Nested()) == 1
    assert seen == [0]
    assert len(_matches(db_session)) == 1


def test_a_document_whose_worker_died_is_taken_again(db_session: Session, matcher, subscribe, ingest) -> None:
    subscribe()
    ingest()
    with pytest.raises(KeyboardInterrupt):

        class Dies:
            def match(self, *args):
                raise KeyboardInterrupt

        process_queue(db_session, Dies())
    db_session.rollback()
    assert process_queue(db_session, matcher) == 0, "still claimed"
    db_session.execute(update(MatchingQueue).values(next_attempt_at=text("now() - interval '1 second'")))
    db_session.commit()
    assert process_queue(db_session, matcher) == 1
    assert len(_matches(db_session)) == 1


def test_a_subscription_deleted_or_paused_meanwhile_gets_no_match(db_session: Session, subscribe, ingest) -> None:
    gone, paused, kept = subscribe(), subscribe(), subscribe()
    ingest()

    kept_id = kept.id
    gone_id, paused_id = gone.id, paused.id

    class Fixed:
        def match(self, *args):
            return [(gone_id, 1.0), (paused_id, 1.0), (kept_id, 0.9), (987654, 1.0)]

    db_session.delete(gone)
    paused.estado = "pausada"
    db_session.commit()
    process_queue(db_session, Fixed())
    assert [m.suscripcion_id for m in _matches(db_session)] == [kept_id]


def test_a_reported_match_is_checked_against_the_filter(db_session: Session, subscribe, ingest) -> None:
    """Precision does not depend on the index being up to date."""
    wrong = subscribe(filters={"a": {"tipo": "seleccion", "valor": "x"}})
    ingest(metadata={"a": "y"})

    class Wrong:
        def match(self, *args):
            return [(wrong_id, 1.0)]

    wrong_id = wrong.id
    process_queue(db_session, Wrong())
    assert _matches(db_session) == []


def test_a_slow_mail_server_does_not_slow_ingestion(db_session: Session, matcher, subscribe, ingest, monkeypatch) -> None:
    subscribe(canales=["correo"])
    sent = []
    monkeypatch.setattr(dispatcher, "enviar_correo", lambda **mail: sent.append(mail))
    ingest()
    assert sent == [], "ingestion does not send email, so it cannot wait for it"
    process_queue(db_session, matcher)
    assert len(sent) == 1


# --- ultima_evaluacion ---


def _last(session: Session, subscription):
    session.refresh(subscription)
    return subscription.ultima_evaluacion


def test_every_active_subscription_counts_as_evaluated_matched_or_not(db_session: Session, matcher, subscribe, ingest) -> None:
    near, far, paused = subscribe(), subscribe(axis(0.0, 1.0)), subscribe(estado="pausada")
    assert _last(db_session, near) is None
    ingest()
    process_queue(db_session, matcher)
    assert _last(db_session, near) == _last(db_session, far) is not None
    assert _last(db_session, paused) is None


def test_a_new_subscription_has_not_been_evaluated_yet(db_session: Session, matcher, subscribe, ingest) -> None:
    subscribe()
    ingest()
    process_queue(db_session, matcher)
    assert _last(db_session, subscribe()) is None


def test_pausing_keeps_the_last_evaluation_and_resuming_does_not_invent_one(
    db_session: Session, matcher, subscribe, ingest
) -> None:
    subscription = subscribe()
    ingest()
    process_queue(db_session, matcher)
    first = _last(db_session, subscription)
    subscription.estado = "pausada"
    db_session.commit()
    assert _last(db_session, subscription) == first
    ingest()
    process_queue(db_session, matcher)
    assert _last(db_session, subscription) == first
    subscription.estado = "activa"
    db_session.commit()
    assert _last(db_session, subscription) == first
    ingest()
    process_queue(db_session, matcher)
    assert _last(db_session, subscription) > first


def test_no_subscription_row_is_written_to_record_an_evaluation(db_session: Session, matcher, subscribe, ingest) -> None:
    subscribe(axis(0.0, 1.0))
    version = text("SELECT xmin::text FROM suscripciones")
    before = db_session.scalar(version)
    ingest()
    process_queue(db_session, matcher)
    assert db_session.scalar(version) == before


# --- worker ---


def _wait(condition, seconds=10) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_the_worker_matches_in_the_background(db_session: Session, subscribe, ingest) -> None:
    subscribe()
    worker = MatchingWorker(db_session.get_bind(), IndexedMatcher(1024), poll_seconds=0.05)
    worker.start()
    try:
        ingest()
        assert _wait(lambda: len(_matches(db_session)) == 1)
        db_session.rollback()
        ingest()
        assert _wait(lambda: len(_matches(db_session)) == 2)
    finally:
        worker.stop()
    assert not worker.is_alive()


def test_the_worker_takes_what_was_left_when_it_starts(db_session: Session, subscribe, ingest) -> None:
    subscribe()
    for _ in range(3):
        ingest()
    worker = MatchingWorker(db_session.get_bind(), IndexedMatcher(1024), poll_seconds=0.05)
    worker.start()
    try:
        assert _wait(lambda: len(_matches(db_session)) == 3)
    finally:
        worker.stop()


def test_the_worker_survives_a_database_error(db_session: Session, subscribe, ingest, monkeypatch) -> None:
    from src.matching import worker as module

    real, calls = module.process_queue, []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("connection lost")
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "process_queue", flaky)
    subscribe()
    ingest()
    worker = MatchingWorker(db_session.get_bind(), SqlLoopMatcher(), poll_seconds=0.02)
    worker.start()
    try:
        assert _wait(lambda: len(_matches(db_session)) == 1)
    finally:
        worker.stop()


def test_the_service_runs_the_worker(db_session: Session, subscribe, ingest, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from src.api import main
    from src.config.installation import InstallationConfig

    monkeypatch.setattr(main, "get_installation_config", lambda: InstallationConfig(nombre="x", seed=False))
    monkeypatch.setattr(main.deps, "_engine", lambda: db_session.get_bind())
    monkeypatch.setattr(main, "get_embedder", lambda: None)
    monkeypatch.setenv("MATCHING_POLL_SECONDS", "0.05")
    subscribe()
    ingest()
    with TestClient(main.app):
        assert _wait(lambda: len(_matches(db_session)) == 1)
