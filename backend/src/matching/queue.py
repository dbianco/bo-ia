"""Matching happens after ingestion, outside its transaction. Ingestion leaves the
document in `matching_queue`; this module takes documents from it, finds their
matches and records them with their notifications."""
from __future__ import annotations

import datetime
import logging

from sqlalchemy import exists, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import (
    Documento,
    EntregaNotificacion,
    EvaluacionMatch,
    MatchingQueue,
    MatchingState,
    Suscripcion,
)
from src.matching.matchers import Matcher
from src.notifications.dispatcher import crear_entregas_para_match
from src.processor.threshold import umbral_configurado
from src.search.filters import cumple_filtros

logger = logging.getLogger("contextcrawl.matching")

LEASE_SECONDS = 300  # after this, the worker that took a document is taken for dead
RETRY_SECONDS = 5  # doubled after each failure
MAX_RETRY_SECONDS = 3600
CHUNK = 1_000

_CLAIM = text(
    """
    UPDATE matching_queue
    SET attempts = attempts + 1, next_attempt_at = clock_timestamp() + make_interval(secs => :lease)
    WHERE documento_id = (
        SELECT documento_id FROM matching_queue WHERE next_attempt_at <= clock_timestamp()
        ORDER BY next_attempt_at, documento_id LIMIT 1 FOR UPDATE SKIP LOCKED
    )
    RETURNING documento_id, attempts
    """
)
_POSTPONE = text(
    """
    UPDATE matching_queue
    SET next_attempt_at = clock_timestamp() + make_interval(secs => :wait), last_error = :error
    WHERE documento_id = :document
    """
)


def enqueue(session: Session, document: Documento) -> None:
    """To be called in the transaction that completes the document."""
    session.add(MatchingQueue(documento_id=document.id))


def process_queue(session: Session, matcher: Matcher, *, limit: int | None = None) -> int:
    """Matches the documents that are due. Returns how many were completed. One
    that fails is left for later, with its error, and does not stop the rest."""
    done = 0
    while limit is None or done < limit:
        claimed = session.execute(_CLAIM, {"lease": LEASE_SECONDS}).one_or_none()
        session.commit()
        if claimed is None:
            break
        document_id, attempts = claimed
        try:
            document = session.get(Documento, document_id)
            if document is not None:
                match_document(session, document, matcher)
            session.execute(MatchingQueue.__table__.delete().where(MatchingQueue.documento_id == document_id))
            session.commit()
            done += 1
        except Exception as exc:
            session.rollback()
            wait = min(RETRY_SECONDS * 2 ** min(attempts - 1, 20), MAX_RETRY_SECONDS)
            logger.exception("Matching document %s failed (attempt %s), again in %s s", document_id, attempts, wait)
            session.execute(_POSTPONE, {"wait": wait, "error": str(exc)[:2000], "document": document_id})
            session.commit()
    return done


def match_document(session: Session, document: Documento, matcher: Matcher) -> None:
    """Finds the matches of a document, records them and notifies. Doing it
    again for the same document adds nothing."""
    # The clock of the database, which is also the one of the subscriptions. Taken
    # first: a subscription created after it may not be considered.
    now = session.scalar(text("SELECT clock_timestamp()"))
    found = matcher.match(session, document, umbral_configurado())
    state = insert(MatchingState).values(id=1, last_run_at=now)
    later = func.greatest(MatchingState.last_run_at, state.excluded.last_run_at)
    session.execute(state.on_conflict_do_update(index_elements=[MatchingState.id], set_={"last_run_at": later}))
    _record(session, document, found, now)
    session.commit()


def _record(
    session: Session, document: Documento, found: list[tuple[int, float]], now: datetime.datetime
) -> None:
    document_id, metadata = document.id, document.metadata_ or {}
    _finish_interrupted(session, document_id)
    recorded = set(
        session.scalars(select(EvaluacionMatch.suscripcion_id).where(EvaluacionMatch.documento_id == document_id))
    )
    scores = {identifier: score for identifier, score in found if identifier not in recorded}
    identifiers = sorted(scores)
    for start in range(0, len(identifiers), CHUNK):
        # The rows decide, not the index: one may have been deleted, paused or
        # changed since. Locked so that none disappears before its match exists.
        rows = session.execute(
            select(Suscripcion.id, Suscripcion.filtros)
            .where(Suscripcion.id.in_(identifiers[start : start + CHUNK]), Suscripcion.estado == "activa")
            .order_by(Suscripcion.id)
            .with_for_update(key_share=True, read=True)
        ).all()
        matches = [
            EvaluacionMatch(
                documento_id=document_id,
                suscripcion_id=identifier,
                score=round(scores[identifier], 4),
                filtros_aplicados=filters,
                fecha_evaluacion=now,
            )
            for identifier, filters in rows
            if cumple_filtros(metadata, filters)
        ]
        session.add_all(matches)
        session.flush()
        match_ids = [match.id for match in matches]
        session.commit()
        for match_id in match_ids:
            match = session.get(EvaluacionMatch, match_id)
            if match is not None:  # the subscription may be deleted at any time
                crear_entregas_para_match(session, match)


def _finish_interrupted(session: Session, document_id: int) -> None:
    """Matches that a crash left without notifications."""
    without = session.scalars(
        select(EvaluacionMatch.id).where(
            EvaluacionMatch.documento_id == document_id,
            ~exists().where(EntregaNotificacion.match_id == EvaluacionMatch.id),
        )
    ).all()
    for match_id in without:
        crear_entregas_para_match(session, session.get(EvaluacionMatch, match_id))
