"""Which subscriptions match a stored document: one interface, two ways.

`SqlLoopMatcher` looks at every subscription, with a query for each: obviously
correct, and the reference. `IndexedMatcher` keeps an index in memory."""
from __future__ import annotations

import os
from threading import Lock
from typing import NamedTuple, Protocol

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.db.models import EMBEDDING_DIM, Documento, Fragmento, Suscripcion
from src.matching.subscription_index import SubscriptionIndex
from src.search.filters import cumple_filtros

LOAD_CHUNK = 2_000


class Found(NamedTuple):
    subscription_id: int
    score: float
    fragment_id: int | None = None  # the fragment with that score; the first one if several tie


class Matcher(Protocol):
    def match(self, session: Session, document: Documento, threshold: float) -> list[Found]:
        """The active subscriptions that match."""
        ...


class SqlLoopMatcher:
    """For each active subscription: applies its filters and, if the document
    passes, asks for its best similarity to the fragments."""

    def match(self, session: Session, document: Documento, threshold: float) -> list[Found]:
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
            best = session.execute(
                select(Fragmento.id, distance)
                .where(Fragmento.documento_id == document.id, Fragmento.embedding.is_not(None))
                .order_by(distance, Fragmento.posicion)
                .limit(1)
            ).one_or_none()
            if best is not None and 1.0 - best[1] >= threshold:
                matches.append(Found(identifier, 1.0 - best[1], best[0]))
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

    def match(self, session: Session, document: Documento, threshold: float) -> list[Found]:
        self.sync(session)
        rows = session.execute(
            select(Fragmento.id, Fragmento.embedding)
            .where(Fragmento.documento_id == document.id, Fragmento.embedding.is_not(None))
            .order_by(Fragmento.posicion)
        ).all()
        if not rows:
            return []
        fragments = np.array([embedding for _, embedding in rows], dtype=np.float32)
        found = sorted(self._index.match(document.metadata_ or {}, fragments, threshold).items())
        best = self._index.best_fragments([identifier for identifier, _ in found], fragments)
        alive = self._alive(session, [identifier for identifier, _ in found])
        for identifier, _ in found:
            if identifier not in alive:
                self._index.remove(identifier)
        return [
            Found(identifier, score, rows[best[identifier]][0]) for identifier, score in found if identifier in alive
        ]

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
