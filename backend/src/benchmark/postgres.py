"""Adapters for the current PostgreSQL implementation.

They run in a database of their own, created for the run and dropped after it:
the corpus goes through the real ingestion path, and must never mix with the
documents or the users of an installation."""
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.api.search import ModoBusqueda, buscar
from src.db.models import Documento, EvaluacionMatch, Suscripcion, Usuario
from src.ingestor.contract import DocumentoNormalizado, ingerir_documento
from src.processor.embeddings import EmbeddingProvider
from src.search.filters import construir_filtros_suscripcion
from src.synthetic.corpus import Corpus

BACKEND_DIR = Path(__file__).resolve().parents[2]
# Results are fragments: ask for more than k documents' worth of them.
FRAGMENTS_PER_DOCUMENT = 4


@contextmanager
def _environment(name: str, value: str) -> Iterator[None]:
    previous = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            del os.environ[name]
        else:
            os.environ[name] = previous


@contextmanager
def scratch_database(server_url: str) -> Iterator[str]:
    """A migrated, empty database on the given server, dropped at the end."""
    base, _, _ = server_url.rpartition("/")
    admin = base.replace("postgresql+psycopg://", "postgresql://") + "/postgres"
    name = f"contextcrawl_benchmark_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        url = f"{base}/{name}"
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "src/db/migrations"))
        with _environment("DATABASE_URL", url):
            command.upgrade(config, "head")
        yield url
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


class _PostgresSystem:
    def __init__(self, url: str, corpus: Corpus, provider: EmbeddingProvider, *, threshold: float) -> None:
        self._engine = create_engine(url)
        self._session: Session = sessionmaker(bind=self._engine)()
        self._corpus = corpus
        self._provider = provider
        self._threshold = str(threshold)

    def close(self) -> None:
        self._session.close()
        self._engine.dispose()

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


class PostgresSearch(_PostgresSystem):
    def __init__(
        self, url: str, corpus: Corpus, provider: EmbeddingProvider, *, mode: str, threshold: float
    ) -> None:
        super().__init__(url, corpus, provider, threshold=threshold)
        self.name = f"postgres-{mode}"
        self._mode = ModoBusqueda(mode)
        stored = set(self._session.scalars(select(Documento.identificador_externo)))
        for document in corpus.documents:
            if document.identificador_externo not in stored:
                ingerir_documento(self._session, provider, document)

    def search(self, query: str, filters: dict[str, str], k: int) -> list[str]:
        with _environment("SIMILARITY_THRESHOLD", self._threshold):
            results = buscar(
                self._session,
                self._provider,
                consulta=query,
                limite=k * FRAGMENTS_PER_DOCUMENT,
                modo=self._mode,
                filtros_solicitados=filters,
                filtros_declarados=list(self._corpus.profile.filters),
            )
        return list(dict.fromkeys(r.identificador_externo for r in results))[:k]


class PostgresMatch(_PostgresSystem):
    """Ingests each document, which evaluates the subscriptions, and reads the
    matches that were recorded."""

    name = "postgres-match"

    def __init__(self, url: str, corpus: Corpus, provider: EmbeddingProvider, *, threshold: float) -> None:
        super().__init__(url, corpus, provider, threshold=threshold)
        user = Usuario(email="benchmark@example.org", password_hash="!")
        self._session.add(user)
        self._session.flush()
        self._ids: dict[int, str] = {}
        for subscription in corpus.truth.subscriptions:
            row = Suscripcion(
                usuario_id=user.id,
                texto_busqueda=subscription.text,
                embedding=provider.embed_query(subscription.text),
                filtros=construir_filtros_suscripcion(subscription.filters, list(corpus.profile.filters)),
            )
            self._session.add(row)
            self._session.flush()
            self._ids[row.id] = subscription.id
        self._session.commit()

    def match(self, document: DocumentoNormalizado) -> set[str]:
        with _environment("SIMILARITY_THRESHOLD", self._threshold):
            result = ingerir_documento(self._session, self._provider, document)
        rows = self._session.scalars(
            select(EvaluacionMatch.suscripcion_id).where(EvaluacionMatch.documento_id == result.documento.id)
        )
        return {self._ids[row] for row in rows}
