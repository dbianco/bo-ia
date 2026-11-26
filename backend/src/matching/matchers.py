"""Which subscriptions match a stored document: one interface, two ways.

`SqlLoopMatcher` looks at every subscription, with a query for each: obviously
correct, and the reference. `IndexedMatcher` keeps an index in memory."""
from __future__ import annotations

import os
from threading import Lock
from typing import Protocol

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from src.db.models import EMBEDDING_DIM, Documento, Fragmento, Suscripcion
from src.matching.subscription_index import SubscriptionIndex
from src.search.filters import cumple_filtros

LOAD_CHUNK = 2_000


class Matcher(Protocol):
    def match(self, session: Session, document: Documento, threshold: float) -> list[tuple[int, float]]:
        """(subscription, score) of the active subscriptions that match."""
        ...


class SqlLoopMatcher:
    """For each active subscription: applies its filters and, if the document
    passes, asks for its best similarity to the fragments."""

    def match(self, session: Session, document: Documento, threshold: float) -> list[tuple[int, float]]:
        matches = []
        subscriptions = session.execute(
            select(Suscripcion.id, Suscripcion.embedding, Suscripcion.filtros)
            .where(Suscripcion.estado == "activa")
            .order_by(Suscripcion.id)
        ).all()
        for identifier, embedding, filters in subscriptions:
            if not cumple_filtros(document.metadata_ or {}, filters):
                continue
            distance = Fragmento.embedding.cosine_distance(embedding)
            best = session.scalar(
                select(func.min(distance)).where(
                    Fragmento.documento_id == document.id, Fragmento.embedding.is_not(None)
                )
            )
            if best is not None and 1.0 - best >= threshold:
                matches.append((identifier, 1.0 - best))
        return matches


class IndexedMatcher:
    """An index of the active subscriptions in this process. PostgreSQL stays the
    system of record: before each document the index reads the subscriptions
    that changed, whoever changed them. It does not learn of deletions, and does
    not need to: whoever records the matches looks at the rows again."""

    def __init__(self, dim: int = EMBEDDING_DIM, **options) -> None:
        self._index = SubscriptionIndex(dim, **options)
        self._seen_up_to = 0  # every transaction before this one is in the index
        self._lock = Lock()

    def match(self, session: Session, document: Documento, threshold: float) -> list[tuple[int, float]]:
        self.sync(session)
        embeddings = session.scalars(
            select(Fragmento.embedding).where(
                Fragmento.documento_id == document.id, Fragmento.embedding.is_not(None)
            )
        ).all()
        if not embeddings:
            return []
        fragments = np.array(embeddings, dtype=np.float32)
        found = sorted(self._index.match(document.metadata_ or {}, fragments, threshold).items())
        alive = self._alive(session, [identifier for identifier, _ in found])
        for identifier, _ in found:
            if identifier not in alive:
                self._index.remove(identifier)
        return [(identifier, score) for identifier, score in found if identifier in alive]

    def sync(self, session: Session) -> int:
        """Brings the index up to date. Returns how many subscriptions changed in it."""
        with self._lock:
            # First the boundary and then the rows: a transaction that is not
            # finished now may commit a change later, and will be asked for again.
            boundary = session.scalar(text("SELECT pg_snapshot_xmin(pg_current_snapshot())::text::bigint"))
            rows = session.execute(
                select(Suscripcion.id, Suscripcion.estado, Suscripcion.filtros, Suscripcion.embedding)
                .where(Suscripcion.changed_xid >= self._seen_up_to)
                .order_by(Suscripcion.id)
                .execution_options(yield_per=LOAD_CHUNK)
            )
            changed = 0
            for chunk in rows.partitions():
                new = []
                for identifier, state, filters, embedding in chunk:
                    vector, active = np.asarray(embedding, dtype=np.float32), state == "activa"
                    if self._index.is_same(identifier, vector, filters):
                        changed += self._index.set_active(identifier, active)
                    elif active or identifier in self._index:
                        new.append((identifier, vector, filters, active))
                self._index.add_many(new)
                changed += len(new)
            self._seen_up_to = boundary
            return changed

    @staticmethod
    def _alive(session: Session, identifiers: list[int]) -> set[int]:
        alive: set[int] = set()
        for start in range(0, len(identifiers), LOAD_CHUNK):
            alive.update(
                session.scalars(
                    select(Suscripcion.id).where(
                        Suscripcion.id.in_(identifiers[start : start + LOAD_CHUNK])
                    )
                )
            )
        return alive


def matcher_from_environment() -> Matcher:
    name = os.environ.get("MATCHING_ENGINE") or "indexed"
    if name == "indexed":
        return IndexedMatcher()
    if name == "loop":
        return SqlLoopMatcher()
    raise ValueError(f"unknown MATCHING_ENGINE {name!r}; choose indexed or loop")
