"""Dependencias de FastAPI: sesión de base de datos y proveedor de
embeddings, inyectables e intercambiables en tests."""
from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.config.installation import InstallationConfig, cargar_installation_config
from src.processor.embeddings import EmbeddingProvider, SentenceTransformerEmbeddingProvider


@lru_cache
def _engine() -> Engine:
    return create_engine(os.environ["DATABASE_URL"])


def get_session() -> Iterator[Session]:
    session_local = sessionmaker(bind=_engine())
    session = session_local()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@lru_cache
def _embedder() -> EmbeddingProvider:
    return SentenceTransformerEmbeddingProvider()


def get_embedder() -> EmbeddingProvider:
    return _embedder()


@lru_cache
def _installation_config() -> InstallationConfig:
    return cargar_installation_config(os.environ["INSTALLATION_CONFIG"])


def get_installation_config() -> InstallationConfig:
    return _installation_config()
