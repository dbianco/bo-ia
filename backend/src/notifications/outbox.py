"""Sends the emails that matching left written.

A worker claims a row by moving its next attempt to the future, sends it, and
records the result. If it dies in between, the row is due again when the lease
ends. Exactly once is not available: if it dies after the server accepted the
message and before that is recorded, the email is sent again, with the same
Message-ID. That window is one commit."""
from __future__ import annotations

import datetime
import hashlib
import logging
from collections.abc import Callable, Sequence

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session, joinedload

from src.db.models import Digest, EntregaNotificacion, EvaluacionMatch, Suscripcion, Usuario
from src.notifications.email import EnvioCorreoFallido, enviar_correo, sender_domain
from src.notifications.render import Rendered, render_alert, render_digest
from src.notifications.settings import NotificationSettings

logger = logging.getLogger("contextcrawl.notifications")

Clock = Callable[[Session], datetime.datetime]

LEASE = datetime.timedelta(minutes=5)  # after this, the worker that claimed a row is taken for dead
RETRY_SECONDS = 60  # doubled after each failure
MAX_RETRY_SECONDS = 3600

# A retry counts when it begins, so that a message that kills its worker is given up too.
_CLAIM = """
    UPDATE {table}
    SET reintentos = reintentos + CASE WHEN fecha_intento IS NULL THEN 0 ELSE 1 END,
        fecha_intento = :now, next_attempt_at = :lease
    WHERE id = (
        SELECT id FROM {table} WHERE estado = 'pendiente' AND next_attempt_at <= :now {extra}
        ORDER BY next_attempt_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
    )
    RETURNING id
"""
_CLAIM_ALERT = text(
    _CLAIM.format(table="entregas_notificacion", extra="AND canal = 'correo' AND frequency = 'immediate'")
)
_CLAIM_DIGEST = text(_CLAIM.format(table="digests", extra=""))


def database_clock(session: Session) -> datetime.datetime:
    return session.scalar(text("SELECT clock_timestamp()"))


def message_id(
    settings: NotificationSettings, kind: str, delivery_ids: Sequence[int], created: datetime.datetime
) -> str:
    """The same for each attempt to send the same deliveries, and for nothing else."""
    what = f"{settings.installation}|{kind}|{','.join(map(str, sorted(delivery_ids)))}|{created.timestamp()}"
    return f"<{hashlib.sha256(what.encode()).hexdigest()[:32]}@{sender_domain()}>"


def send_pending(
    session: Session, settings: NotificationSettings, *, clock: Clock = database_clock, limit: int | None = None
) -> int:
    """Sends what is due. Returns how many emails were sent. If the server does
    not work it stops: the others are still due."""
    sent = 0
    for claim, send in ((_CLAIM_ALERT, _send_alert), (_CLAIM_DIGEST, _send_digest)):
        while limit is None or sent < limit:
            now = clock(session)
            identifier = session.scalar(claim, {"now": now, "lease": now + LEASE})
            session.commit()
            if identifier is None:
                break
            try:
                sent += send(session, settings, identifier, now)
            except EnvioCorreoFallido as exc:
                if exc.server:
                    return sent
    return sent


def _send_alert(session: Session, settings: NotificationSettings, identifier: int, now: datetime.datetime) -> bool:
    delivery = session.get(
        EntregaNotificacion,
        identifier,
        options=[joinedload(EntregaNotificacion.match).joinedload(EvaluacionMatch.suscripcion)],
        populate_existing=True,
    )
    if delivery is None:  # its subscription was deleted
        return False
    return _attempt(
        session,
        settings,
        delivery,
        [delivery],
        now,
        delivery.match.suscripcion.usuario.email,
        lambda: render_alert(settings, delivery.match, now),
        message_id(settings, "alert", [delivery.id], delivery.created_at),
    )


def _send_digest(session: Session, settings: NotificationSettings, identifier: int, now: datetime.datetime) -> bool:
    digest = session.get(Digest, identifier, populate_existing=True)
    if digest is None:  # its user was deleted
        return False
    deliveries = session.scalars(
        select(EntregaNotificacion)
        .where(EntregaNotificacion.digest_id == identifier)
        .options(
            joinedload(EntregaNotificacion.match).joinedload(EvaluacionMatch.documento),
            joinedload(EntregaNotificacion.match).joinedload(EvaluacionMatch.fragmento),
            joinedload(EntregaNotificacion.match)
            .joinedload(EvaluacionMatch.suscripcion)
            .defer(Suscripcion.embedding),
        )
        .order_by(EntregaNotificacion.id)
    ).all()
    if not deliveries:  # its subscriptions were deleted
        session.delete(digest)
        session.commit()
        return False
    return _attempt(
        session,
        settings,
        digest,
        deliveries,
        now,
        session.get(Usuario, digest.usuario_id).email,
        lambda: render_digest(settings, digest.frequency, [d.match for d in deliveries], now),
        message_id(settings, "digest", [d.id for d in deliveries], digest.created_at),
    )


def _attempt(
    session: Session,
    settings: NotificationSettings,
    claimed: EntregaNotificacion | Digest,
    deliveries: Sequence[EntregaNotificacion],
    now: datetime.datetime,
    recipient: str,
    render: Callable[[], Rendered],
    identifier: str,
) -> bool:
    """Sends what was claimed. True if it was sent; raises if it is the server that does not work."""
    if claimed.reintentos > settings.max_retries:  # its workers died each time
        _record_failure(session, claimed, deliveries, claimed.error_proveedor or "Se agotaron los reintentos")
        return False
    try:
        rendered = render()
        enviar_correo(
            destinatario=recipient,
            asunto=rendered.subject,
            cuerpo=rendered.text,
            html=rendered.html,
            message_id=identifier,
        )
    except EnvioCorreoFallido as exc:
        if exc.permanent or claimed.reintentos >= settings.max_retries:
            _record_failure(session, claimed, deliveries, str(exc))
        else:
            _record_retry(session, claimed, now, str(exc))
        raise
    except Exception as exc:  # a mistake of ours must not stop the other emails
        logger.exception("Unexpected error sending to the user of delivery %s", claimed.id)
        session.rollback()
        session.refresh(claimed)
        if claimed.reintentos >= settings.max_retries:
            _record_failure(session, claimed, deliveries, str(exc))
        else:
            _record_retry(session, claimed, now, str(exc))
        return False
    _record_sent(session, claimed, deliveries, now)
    session.commit()
    return True


def _record_sent(session: Session, claimed, deliveries: Sequence[EntregaNotificacion], now: datetime.datetime) -> None:
    claimed.estado = "entregada"
    claimed.error_proveedor = None
    _update(session, deliveries, estado="entregada", fecha_intento=now, error_proveedor=None)


def _record_failure(session: Session, claimed, deliveries: Sequence[EntregaNotificacion], error: str) -> None:
    claimed.estado = "fallida"
    claimed.error_proveedor = error[:2000]
    _update(session, deliveries, estado="fallida", error_proveedor=error[:2000])
    session.commit()


def _record_retry(session: Session, claimed, now: datetime.datetime, error: str) -> None:
    wait = min(RETRY_SECONDS * 2 ** min(claimed.reintentos, 20), MAX_RETRY_SECONDS)
    claimed.next_attempt_at = now + datetime.timedelta(seconds=wait)
    claimed.error_proveedor = error[:2000]
    session.commit()


def _update(session: Session, deliveries: Sequence[EntregaNotificacion], **values) -> None:
    session.execute(
        update(EntregaNotificacion).where(EntregaNotificacion.id.in_([d.id for d in deliveries])).values(**values)
    )
