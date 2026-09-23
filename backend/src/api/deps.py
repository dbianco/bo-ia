"""Dependencias de FastAPI: sesión de base de datos y proveedor de
embeddings, inyectables e intercambiables en tests."""
from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache

from fastapi import Depends, HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.auth.sessions import obtener_usuario_de_sesion
from src.config.installation import InstallationConfig, cargar_installation_config
from src.db.models import Usuario
from src.processor.embeddings import EmbeddingProvider, SentenceTransformerEmbeddingProvider

COOKIE_SESION = "bo_ia_sesion"


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


def get_usuario_actual(request: Request, session: Session = Depends(get_session)) -> Usuario:
    """FR-005: 401 si no hay una sesión válida. Usado por los endpoints
    que gestionan las suscripciones propias de un usuario; `GET
    /v1/search` y `GET /v1/config` no la usan y siguen públicos (FR-006)."""
    token = request.cookies.get(COOKIE_SESION)
    usuario = obtener_usuario_de_sesion(session, token) if token else None
    if usuario is None:
        raise HTTPException(status_code=401, detail="No autenticado")
    return usuario
