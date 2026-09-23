"""Modos HYBRID/ALL del endpoint de búsqueda: consultas de una sola
palabra no siempre superan el umbral vectorial aunque el término aparezca
literalmente en el texto."""
import datetime
import math

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_installation_config, get_session
from src.api.main import app
from src.config.installation import InstallationConfig
from src.db.models import Documento, Fragmento, Fuente

DIM = 1024


def _one_hot(indice: int, dim: int = DIM) -> list[float]:
    v = [0.0] * dim
    v[indice] = 1.0
    return v


def _normalizado(v: list[float]) -> list[float]:
    norma = math.sqrt(sum(c * c for c in v))
    return [c / norma for c in v]


class _VectorFijoEmbeddingProvider:
    def __init__(self, vectores: dict[str, list[float]]) -> None:
        self._vectores = vectores

    def embed_query(self, texto: str) -> list[float]:
        return self._vectores[texto]

    def embed_passage(self, texto: str) -> list[float]:
        return self._vectores[texto]


VECTOR_QUERY_SALUD = _one_hot(0)
# Similitud baja a propósito (~0.29, por debajo del umbral de 0.5): reproduce
# el caso real donde el vector de una palabra suelta no supera el umbral
# aunque el texto la contenga literalmente.
VECTOR_FRAGMENTO_SALUD = _normalizado([0.3, 1.0] + [0.0] * (DIM - 2))
VECTOR_IRRELEVANTE = _one_hot(1)


def _crear_documento_con_fragmento(
    session: Session, *, sufijo: str, fecha: datetime.date, embedding: list[float], texto: str
) -> Fragmento:
    fuente = session.query(Fuente).filter_by(clave="cordoba").one_or_none()
    if fuente is None:
        fuente = Fuente(clave="cordoba", nombre="cordoba", config={})
        session.add(fuente)
        session.flush()
    documento = Documento(
        fuente_id=fuente.id,
        identificador_externo=f"BO-{sufijo}",
        fecha=fecha,
        texto=texto,
        url_fuente=f"https://boletinoficial.cba.gov.ar/{sufijo}",
        hash_contenido=f"hash-{sufijo}",
        estado="completo",
    )
    session.add(documento)
    session.flush()
    fragmento = Fragmento(documento_id=documento.id, posicion=0, texto=texto, fecha=fecha, embedding=embedding)
    session.add(fragmento)
    session.flush()
    return fragmento


@pytest.fixture()
def client(db_session: Session):
    provider = _VectorFijoEmbeddingProvider({"salud": VECTOR_QUERY_SALUD})

    def _get_session_override():
        yield db_session

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[get_embedder] = lambda: provider
    app.dependency_overrides[get_installation_config] = lambda: InstallationConfig(nombre="test")
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_modo_semantic_no_encuentra_termino_con_similitud_vectorial_baja(
    client: TestClient, db_session: Session
) -> None:
    """Reproduce el hallazgo real: en SEMANTIC (default), el umbral
    descarta el resultado aunque el texto contenga la palabra."""
    _crear_documento_con_fragmento(
        db_session,
        sufijo="salud-bajo",
        fecha=datetime.date(2026, 1, 1),
        embedding=VECTOR_FRAGMENTO_SALUD,
        texto="Resolución del Ministerio de Salud sobre vacunación.",
    )

    respuesta = client.get("/v1/search", params={"q": "salud"})

    assert respuesta.json()["total"] == 0


def test_modo_hybrid_rescata_por_coincidencia_de_texto(client: TestClient, db_session: Session) -> None:
    """En HYBRID, una coincidencia de texto exacto rescata un resultado
    aunque su similitud vectorial esté bajo el umbral."""
    _crear_documento_con_fragmento(
        db_session,
        sufijo="salud-bajo",
        fecha=datetime.date(2026, 1, 1),
        embedding=VECTOR_FRAGMENTO_SALUD,
        texto="Resolución del Ministerio de Salud sobre vacunación.",
    )
    _crear_documento_con_fragmento(
        db_session,
        sufijo="irrelevante",
        fecha=datetime.date(2026, 1, 2),
        embedding=VECTOR_IRRELEVANTE,
        texto="Licitación para repavimentar una ruta provincial.",
    )

    respuesta = client.get("/v1/search", params={"q": "salud", "mode": "hybrid"})
    cuerpo = respuesta.json()

    assert cuerpo["total"] == 1
    assert cuerpo["resultados"][0]["identificador_externo"] == "BO-salud-bajo"
    assert cuerpo["resultados"][0]["coincidencia_texto"] is True


def test_modo_hybrid_sigue_exigiendo_umbral_sin_coincidencia_de_texto(
    client: TestClient, db_session: Session
) -> None:
    """Sin match de texto, HYBRID se comporta como SEMANTIC: exige el
    umbral vectorial."""
    _crear_documento_con_fragmento(
        db_session,
        sufijo="bajo-sin-texto",
        fecha=datetime.date(2026, 1, 1),
        embedding=VECTOR_FRAGMENTO_SALUD,
        texto="Un texto que no menciona el término de la consulta para nada.",
    )

    respuesta = client.get("/v1/search", params={"q": "salud", "mode": "hybrid"})

    assert respuesta.json()["total"] == 0


def test_modo_all_no_aplica_ningun_umbral(client: TestClient, db_session: Session) -> None:
    """ALL es unión sin filtrar, ni por vector ni por texto."""
    _crear_documento_con_fragmento(
        db_session,
        sufijo="bajo-sin-texto",
        fecha=datetime.date(2026, 1, 1),
        embedding=VECTOR_FRAGMENTO_SALUD,
        texto="Un texto que no menciona el término de la consulta para nada.",
    )

    respuesta = client.get("/v1/search", params={"q": "salud", "mode": "all"})

    assert respuesta.json()["total"] == 1


def test_modo_invalido_devuelve_422(client: TestClient) -> None:
    respuesta = client.get("/v1/search", params={"q": "salud", "mode": "invalido"})
    assert respuesta.status_code == 422
