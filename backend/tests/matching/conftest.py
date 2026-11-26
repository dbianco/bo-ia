import datetime
import itertools

import pytest
from sqlalchemy.orm import Session

from src.db.models import Documento, Suscripcion, Usuario
from src.ingestor.contract import DocumentoNormalizado, ingerir_documento

DIM = 1024


def axis(*weights: float) -> list[float]:
    """A unit vector with the given first coordinates (and the rest of the norm in the last one)."""
    vector = list(weights) + [0.0] * (DIM - len(weights))
    vector[-1] = max(0.0, 1 - sum(w * w for w in weights)) ** 0.5
    return vector


class FixedEmbedder:
    """Embeds "v:0.8,0.1" as axis(0.8, 0.1), and anything else as axis(1)."""

    def embed_passage(self, text: str) -> list[float]:
        text = text.split()[0]
        return axis(*(float(x) for x in text[2:].split(","))) if text.startswith("v:") else axis(1.0)

    embed_query = embed_passage


@pytest.fixture()
def embedder() -> FixedEmbedder:
    return FixedEmbedder()


@pytest.fixture()
def user(db_session: Session) -> Usuario:
    user = Usuario(email="a@example.org", password_hash="x")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def subscribe(db_session: Session, user: Usuario):
    def make(vector=None, filters=None, estado="activa", canales=()) -> Suscripcion:
        subscription = Suscripcion(
            usuario_id=user.id,
            texto_busqueda="x",
            embedding=vector or axis(1.0),
            filtros=filters or {},
            estado=estado,
            canales=list(canales),
        )
        db_session.add(subscription)
        db_session.commit()
        return subscription

    return make


@pytest.fixture()
def ingest(db_session: Session, embedder: FixedEmbedder):
    numbers = itertools.count()

    def make(text: str = "texto", metadata=None, **options) -> Documento:
        n = next(numbers)
        document = DocumentoNormalizado(
            "f", f"d{n}", datetime.date(2026, 1, 1), f"{text} {n}", "https://example.org", metadata=metadata or {}
        )
        return ingerir_documento(db_session, embedder, document, **options).documento

    return make
