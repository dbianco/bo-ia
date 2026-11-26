"""Daily and weekly digests: one email per user and period.

A match is in a digest because its delivery says so (`digest_id`), and that is
written once, together with the digest. A match whose transaction ends after its
digest was built is still without one, and goes to the next: never to both, and
never to neither."""
from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import Digest, EntregaNotificacion, EvaluacionMatch, Suscripcion
from src.notifications.outbox import Clock, database_clock
from src.notifications.settings import NotificationSettings

FREQUENCIES = ("daily", "weekly")


def last_boundary(
    now: datetime.datetime, frequency: str, zone: ZoneInfo, hour: int
) -> datetime.datetime:
    """When the last period ended: at that hour of the day, or of Monday, in the
    local time of the installation."""
    local = now.astimezone(zone)
    day = local.date()
    if frequency == "weekly":
        day -= datetime.timedelta(days=day.weekday())
    boundary = datetime.datetime.combine(day, datetime.time(hour), tzinfo=zone)
    if boundary > local:
        day -= datetime.timedelta(days=7 if frequency == "weekly" else 1)
        boundary = datetime.datetime.combine(day, datetime.time(hour), tzinfo=zone)
    return boundary.astimezone(datetime.UTC)


def build_digests(session: Session, settings: NotificationSettings, *, clock: Clock = database_clock) -> int:
    """Writes the digests of the periods that have ended, for the users who have
    something in them. Returns how many. After a time without running there is one
    with everything. Sending them is of the outbox."""
    now, zone = clock(session), ZoneInfo(settings.timezone)
    built = 0
    for frequency in FREQUENCIES:
        boundary = last_boundary(now, frequency, zone, settings.digest_hour)
        waiting = (
            select(EntregaNotificacion.id)
            .join(EvaluacionMatch, EntregaNotificacion.match_id == EvaluacionMatch.id)
            .join(Suscripcion, EvaluacionMatch.suscripcion_id == Suscripcion.id)
            .where(
                EntregaNotificacion.canal == "correo",
                EntregaNotificacion.estado == "pendiente",
                EntregaNotificacion.frequency == frequency,
                EntregaNotificacion.digest_id.is_(None),
                EntregaNotificacion.created_at < boundary,
            )
        )
        users = session.scalars(waiting.with_only_columns(Suscripcion.usuario_id).distinct()).all()
        session.commit()
        for user_id in users:
            built += _build(session, frequency, boundary, user_id, waiting, now)
    return built


def _build(session: Session, frequency: str, boundary: datetime.datetime, user_id: int, waiting, now) -> bool:
    # Two workers: the second waits here for the first, and finds that it exists.
    digest_id = session.scalar(
        insert(Digest)
        .values(usuario_id=user_id, frequency=frequency, period_end=boundary, next_attempt_at=now)
        .on_conflict_do_nothing(constraint="uq_digest_usuario_frequency_period")
        .returning(Digest.id)
    )
    claimed = 0
    if digest_id is not None:
        claimed = session.execute(
            update(EntregaNotificacion)
            .where(EntregaNotificacion.id.in_(waiting.where(Suscripcion.usuario_id == user_id)))
            .values(digest_id=digest_id)
            .execution_options(synchronize_session=False)
        ).rowcount
    if not claimed:
        session.rollback()
        return False
    session.commit()
    return True
