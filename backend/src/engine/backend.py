"""Who answers a search: PostgreSQL (the reference) or the in-process engine.

PostgreSQL stays the system of record. The engine is built from it, reads what
changed before each search, and the rows of its results are read from it."""
from __future__ import annotations

import logging
import os
import threading
from datetime import date
from typing import Protocol

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.config.installation import Filtro
from src.db.models import EMBEDDING_DIM, SUPERSEDED, Documento, Fragmento
from src.engine.engine import EngineFragment, SearchEngine
from src.processor.embeddings import EmbeddingProvider
from src.processor.threshold import umbral_configurado
from src.search import postgres
from src.search.results import ModoBusqueda, ResultadoBusqueda, resultado_desde

logger = logging.getLogger("contextcrawl.engine")

LOAD_CHUNK = 500  # documents
DEFAULT_POLL_SECONDS = 1.0
LOCK_SECONDS = 0.05  # how long a search waits for another thread to finish a refresh
ATTEMPTS = 3


class SearchBackend(Protocol):
    def start(self, engine: Engine) -> None:
        """Whatever it needs to run in the background."""
        ...

    def stop(self) -> None: ...

    def search(
        self,
        session: Session,
        embedder: EmbeddingProvider,
        *,
        consulta: str,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
        limite: int = 10,
        modo: ModoBusqueda = ModoBusqueda.semantic,
        filtros_solicitados: dict[str, str] | None = None,
        filtros_declarados: list[Filtro] | None = None,
    ) -> list[ResultadoBusqueda]: ...


class PostgresBackend:
    def start(self, engine: Engine) -> None:
        pass

    def stop(self) -> None:
        pass

    def search(self, session: Session, embedder: EmbeddingProvider, **options) -> list[ResultadoBusqueda]:
        return postgres.buscar(session, embedder, **options)


class EngineBackend:
    def __init__(self, dim: int = EMBEDDING_DIM, **options) -> None:
        self._engine = SearchEngine(dim, **options)
        self._seen_up_to = 0  # every transaction before this one is in the engine
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.ready = False

    # --- keeping it current ---

    def start(self, engine: Engine, poll_seconds: float = DEFAULT_POLL_SECONDS) -> None:
        """Loads in the background, and then refreshes even if nobody searches."""
        sessions = sessionmaker(bind=engine)

        def run() -> None:
            while not self._stop.is_set():
                try:
                    with sessions() as session:
                        self.sync(session)
                except Exception:
                    logger.exception("The search engine could not be refreshed")
                self._stop.wait(poll_seconds)

        self._thread = threading.Thread(target=run, name="search-engine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(30)

    def sync(self, session: Session) -> int:
        """Reads the documents that changed. Returns how many there were."""
        with self._lock:
            return self._sync(session)

    def _sync(self, session: Session) -> int:
        # First the boundary and then the rows: a transaction that is not finished
        # now may commit a change later, and will be asked for again.
        boundary = session.scalar(text("SELECT pg_snapshot_xmin(pg_current_snapshot())::text::bigint"))
        changed = self._load(session, self._seen_up_to)
        self._seen_up_to = boundary
        if not self.ready:
            self._engine.warm_up()
            self.ready = True
            logger.info("Search engine ready: %s documents, %s fragments", len(self._engine), self._engine.rows)
        return changed

    def _load(self, session: Session, since: int) -> int:
        documents = session.execute(
            select(Documento.id, Documento.estado, Documento.fecha, Documento.metadata_)
            .where(Documento.changed_xid >= since)
            .order_by(Documento.id)
        ).all()
        changed = 0
        for start in range(0, len(documents), LOAD_CHUNK):
            if self._stop.is_set():
                raise RuntimeError("stopped while loading")
            changed += self._load_chunk(session, documents[start : start + LOAD_CHUNK])
        return changed

    def _load_chunk(self, session: Session, documents) -> int:
        fragments: dict[int, list[EngineFragment]] = {}
        rows = session.execute(
            select(Fragmento.documento_id, Fragmento.id, Fragmento.texto, Fragmento.embedding)
            .where(Fragmento.documento_id.in_([d.id for d in documents]))
            .order_by(Fragmento.documento_id, Fragmento.posicion)
        )
        for document_id, fragment_id, content, embedding in rows:
            vector = None if embedding is None else np.asarray(embedding, dtype=np.float32)
            fragments.setdefault(document_id, []).append(EngineFragment(fragment_id, content, vector))
        new, changed = [], 0
        for document_id, state, day, metadata in documents:
            own = fragments.get(document_id, [])
            if state == SUPERSEDED or not own:
                if document_id in self._engine:
                    self._engine.remove(document_id)
                    changed += 1
            elif document_id in self._engine and self._same(document_id, own):
                changed += self._engine.update(document_id, day, metadata or {})
            else:
                new.append((document_id, day, metadata or {}, own))
        self._engine.put_many(new)
        return changed + len(new)

    def _same(self, document_id: int, fragments: list[EngineFragment]) -> bool:
        stored = self._engine.fragments_of(document_id)
        return len(stored) == len(fragments) and all(
            s.fragment_id == f.fragment_id and s.text_hash == hash(f.text) and _equal(s.vector, f.vector)
            for s, f in zip(stored, fragments, strict=True)
        )

    # --- search ---

    def search(
        self,
        session: Session,
        embedder: EmbeddingProvider,
        *,
        consulta: str,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
        limite: int = 10,
        modo: ModoBusqueda = ModoBusqueda.semantic,
        filtros_solicitados: dict[str, str] | None = None,
        filtros_declarados: list[Filtro] | None = None,
    ) -> list[ResultadoBusqueda]:
        if self._lock.acquire(timeout=LOCK_SECONDS):
            try:
                self._sync(session)
            finally:
                self._lock.release()
        elif not self.ready:
            return postgres.buscar(
                session,
                embedder,
                consulta=consulta,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                limite=limite,
                modo=modo,
                filtros_solicitados=filtros_solicitados,
                filtros_declarados=filtros_declarados,
            )

        vector = embedder.embed_query(consulta)
        results: list[ResultadoBusqueda] = []
        for _ in range(ATTEMPTS):
            hits = self._engine.search(
                consulta,
                vector,
                mode=modo.value,
                limit=limite,
                threshold=umbral_configurado(),
                filters=filtros_solicitados,
                filters_declared=filtros_declarados or (),
                date_from=fecha_desde,
                date_to=fecha_hasta,
            )
            rows = {
                fragment.id: (fragment, document)
                for fragment, document in session.execute(
                    select(Fragmento, Documento)
                    .join(Documento, Fragmento.documento_id == Documento.id)
                    .where(Fragmento.id.in_([h.fragment_id for h in hits]), Documento.estado != SUPERSEDED)
                )
            }
            results = [
                resultado_desde(h.fragment_id, *rows[h.fragment_id], h.similarity, h.text_match)
                for h in hits
                if h.fragment_id in rows
            ]
            gone = {h.document_id for h in hits if h.fragment_id not in rows}
            if not gone:
                break
            # The engine does not learn of deleted documents until it finds one.
            for document_id in gone:
                self._engine.remove(document_id)
        return results


def _equal(stored: np.ndarray | None, new: np.ndarray | None) -> bool:
    if stored is None or new is None:
        return stored is new
    norm = np.linalg.norm(new)
    return np.allclose(stored, new / norm if norm else new, atol=1e-6)


def backend_from_environment() -> SearchBackend:
    name = os.environ.get("SEARCH_ENGINE") or "postgres"
    if name == "postgres":
        return PostgresBackend()
    if name == "engine":
        weights = (os.environ.get("RRF_WEIGHTS") or "1,1").split(",")
        try:
            vector_weight, text_weight = (float(w) for w in weights)
        except ValueError as exc:
            raise ValueError("RRF_WEIGHTS must be two numbers: vector,text") from exc
        return EngineBackend(fusion_weights=(vector_weight, text_weight))
    raise ValueError(f"unknown SEARCH_ENGINE {name!r}; choose postgres or engine")
