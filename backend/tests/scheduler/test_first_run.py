"""Plan 15, defect B: a source runs when it is due, however often the backend restarts."""
import datetime
import threading
import time

import pytest
from sqlalchemy.orm import Session

from src import scheduler as module
from src.config.installation import ConectorConfig, FuenteConfig, InstallationConfig
from src.db.models import EjecucionFuente, Fuente
from src.processor.embeddings import FakeEmbeddingProvider
from src.scheduler import detener_scheduler, first_runs, iniciar_scheduler

NOW = datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.UTC)
DAY = datetime.timedelta(days=1)
HOUR = datetime.timedelta(hours=1)
SOON = datetime.timedelta(minutes=5)


def _installation(*sources: tuple[str, float]) -> InstallationConfig:
    return InstallationConfig(
        nombre="x",
        fuentes=[
            FuenteConfig(clave=key, nombre=key, conector=ConectorConfig(tipo="fake", frecuencia_minutos=minutes))
            for key, minutes in sources
        ]
        + [FuenteConfig(clave="manual", nombre="manual")],
    )


DAILY = _installation(("a", 24 * 60))


@pytest.fixture()
def record(db_session: Session):
    sources: dict[str, Fuente] = {}

    def add(key: str, at: datetime.datetime, state: str = "completada") -> None:
        if key not in sources:
            sources[key] = Fuente(clave=key, nombre=key, config={})
            db_session.add(sources[key])
            db_session.flush()
        db_session.add(
            EjecucionFuente(fuente_id=sources[key].id, inicio=at, fin=at, estado=state, version_conector="v")
        )
        db_session.commit()

    return add


def test_a_source_that_never_ran_runs_soon(db_session: Session) -> None:
    runs = first_runs(db_session, DAILY, NOW)
    assert list(runs) == ["a"], "a source without connector is not scheduled"
    assert NOW < runs["a"] <= NOW + SOON


def test_an_overdue_source_runs_soon(db_session: Session, record) -> None:
    record("a", NOW - 3 * DAY)
    assert NOW < first_runs(db_session, DAILY, NOW)["a"] <= NOW + SOON


def test_a_source_that_is_not_due_waits_for_its_time(db_session: Session, record) -> None:
    record("a", NOW - 10 * HOUR)
    assert first_runs(db_session, DAILY, NOW)["a"] == NOW + 14 * HOUR


def test_the_last_successful_run_counts(db_session: Session, record) -> None:
    record("a", NOW - 30 * HOUR)
    record("a", NOW - 40 * HOUR)
    for state in ("fallida", "en_curso"):
        record("a", NOW - HOUR, state)
    assert first_runs(db_session, DAILY, NOW)["a"] <= NOW + SOON
    record("a", NOW - 2 * HOUR, "partial")
    assert first_runs(db_session, DAILY, NOW)["a"] == NOW + 22 * HOUR


def test_the_runs_of_another_source_do_not_count(db_session: Session, record) -> None:
    record("b", NOW - HOUR)
    assert first_runs(db_session, DAILY, NOW)["a"] <= NOW + SOON


def test_overdue_sources_do_not_start_at_once(db_session: Session) -> None:
    runs = sorted(first_runs(db_session, _installation(*((f"s{i}", 60) for i in range(6))), NOW).values())
    gaps = [b - a for a, b in zip(runs, runs[1:], strict=False)]
    assert len(runs) == 6 and min(gaps) >= datetime.timedelta(seconds=10)


@pytest.mark.parametrize(("interval_hours", "restart_hours"), [(24, 5), (24, 23), (24, 1), (720, 20), (3, 1)])
def test_a_backend_that_restarts_often_keeps_the_schedule(
    db_session: Session, record, interval_hours: int, restart_hours: int
) -> None:
    """A backend restarted more often than the interval, with a clock that moves
    only when the test says so."""
    installation = _installation(("a", interval_hours * 60))
    interval, restart = interval_hours * HOUR, restart_hours * HOUR
    clock, ran = NOW, []
    while clock < NOW + 4 * interval:
        due = first_runs(db_session, installation, clock)["a"]
        next_restart = clock + restart
        while due < next_restart:  # while it is up, the job repeats with its interval
            ran.append(due)
            record("a", due)
            due += interval
        clock = next_restart
    assert len(ran) in (4, 5)
    gaps = [b - a for a, b in zip(ran, ran[1:], strict=False)]
    assert all(interval <= gap <= interval + restart + SOON for gap in gaps), "neither before its time nor much later"


class _Connector:
    def descubrir(self, *, fuente_clave, config):
        return iter(())


def _start(db_session: Session, installation: InstallationConfig, connector=_Connector, **options):
    return iniciar_scheduler(
        installation, db_session.get_bind(), FakeEmbeddingProvider(), conectores={"fake": connector}, **options
    )


def test_the_job_is_scheduled_at_that_time_and_repeats(db_session: Session, record) -> None:
    now = datetime.datetime.now(datetime.UTC)
    record("a", now - 10 * HOUR)
    scheduler = _start(db_session, DAILY)
    try:
        (job,) = scheduler.get_jobs()
        assert abs(job.next_run_time - (now + 14 * HOUR)) < datetime.timedelta(seconds=5)
        following = job.trigger.get_next_fire_time(job.next_run_time, job.next_run_time)
        assert following - job.next_run_time == DAY
    finally:
        detener_scheduler(scheduler)


def test_a_late_job_is_not_skipped(db_session: Session) -> None:
    """The default of the library drops a job that starts more than a second late."""
    scheduler = _start(db_session, DAILY)
    try:
        assert scheduler.get_jobs()[0].misfire_grace_time is None
    finally:
        detener_scheduler(scheduler)


def test_startup_does_not_wait_and_few_run_at_once(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(module, "STARTUP_DELAY", datetime.timedelta(seconds=0.2))
    monkeypatch.setattr(module, "STARTUP_GAP", datetime.timedelta(seconds=0))
    running, most, done, lock = 0, 0, [], threading.Lock()

    class Slow:
        def descubrir(self, *, fuente_clave, config):
            nonlocal running, most
            with lock:
                running += 1
                most = max(most, running)
            time.sleep(0.4)
            with lock:
                running -= 1
                done.append(fuente_clave)
            return iter(())

    keys = [f"s{i}" for i in range(5)]
    db_session.add_all(Fuente(clave=k, nombre=k, config={}) for k in keys)
    db_session.commit()
    scheduler = _start(db_session, _installation(*((k, 60) for k in keys)), Slow)
    try:
        assert done == [], "starting does not wait for the runs"
        end = time.monotonic() + 20
        while len(done) < 5 and time.monotonic() < end:
            time.sleep(0.05)
        assert sorted(done) == keys
        assert most <= module.MAX_CONCURRENT_RUNS < 5
    finally:
        detener_scheduler(scheduler)
