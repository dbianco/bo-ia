"""T015: endpoint de búsqueda — consulta en lenguaje natural, filtros de
fecha, orden por relevancia, límite de resultados, metadatos de cita,
lista vacía cuando no hay resultados confiables (FR-008 a FR-013, FR-015).
"""
import datetime
import math

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_session
from src.api.main import app
from src.db.models import Boletin, Fragmento

DIM = 1024


def _one_hot(indice: int, dim: int = DIM) -> list[float]:
    v = [0.0] * dim
    v[indice] = 1.0
    return v


def _normalizado(v: list[float]) -> list[float]:
    norma = math.sqrt(sum(c * c for c in v))
    return [c / norma for c in v]


class _VectorFijoEmbeddingProvider:
    """Stub de test: devuelve vectores fijos, elegidos para que la
    similitud coseno con la consulta sea exactamente conocida."""

    def __init__(self, vectores: dict[str, list[float]]) -> None:
        self._vectores = vectores

    def embed_query(self, texto: str) -> list[float]:
        return self._vectores[texto]

    def embed_passage(self, texto: str) -> list[float]:
        return self._vectores[texto]


VECTOR_ALTO = _one_hot(0)  # similitud 1.0 con la consulta
VECTOR_MEDIO = _normalizado([1.0, 1.0] + [0.0] * (DIM - 2))  # similitud ~0.707
VECTOR_BAJO = _one_hot(1)  # similitud 0.0 con la consulta


def _crear_boletin_con_fragmento(
    session: Session, *, sufijo: str, fecha: datetime.date, embedding: list[float], texto: str = "texto"
) -> Fragmento:
    boletin = Boletin(
        jurisdiccion="cordoba",
        identificador_oficial=f"BO-{sufijo}",
        fecha_publicacion=fecha,
        texto_original=texto,
        url_oficial=f"https://boletinoficial.cba.gov.ar/{sufijo}",
        hash_contenido=f"hash-{sufijo}",
        estado_ingesta="completo",
    )
    session.add(boletin)
    session.flush()
    fragmento = Fragmento(
        boletin_id=boletin.id, posicion=0, texto=texto, fecha_publicacion=fecha, embedding=embedding
    )
    session.add(fragmento)
    session.flush()
    return fragmento


@pytest.fixture()
def client(db_session: Session):
    provider = _VectorFijoEmbeddingProvider({"consulta de prueba": VECTOR_ALTO})

    def _get_session_override():
        yield db_session

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[get_embedder] = lambda: provider
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_busqueda_ordena_por_relevancia_y_aplica_umbral(client: TestClient, db_session: Session) -> None:
    _crear_boletin_con_fragmento(db_session, sufijo="alto", fecha=datetime.date(2026, 1, 10), embedding=VECTOR_ALTO)
    _crear_boletin_con_fragmento(db_session, sufijo="medio", fecha=datetime.date(2026, 1, 11), embedding=VECTOR_MEDIO)
    _crear_boletin_con_fragmento(db_session, sufijo="bajo", fecha=datetime.date(2026, 1, 12), embedding=VECTOR_BAJO)

    respuesta = client.get("/v1/search", params={"q": "consulta de prueba"})

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    identificadores = [r["identificador_oficial"] for r in cuerpo["resultados"]]
    # El de baja similitud (0.0) queda por debajo del umbral por defecto (0.5).
    assert identificadores == ["BO-alto", "BO-medio"]


def test_busqueda_filtra_por_intervalo_de_fechas(client: TestClient, db_session: Session) -> None:
    _crear_boletin_con_fragmento(db_session, sufijo="viejo", fecha=datetime.date(2020, 1, 1), embedding=VECTOR_ALTO)
    _crear_boletin_con_fragmento(db_session, sufijo="nuevo", fecha=datetime.date(2026, 6, 1), embedding=VECTOR_ALTO)

    respuesta = client.get(
        "/v1/search",
        params={"q": "consulta de prueba", "date_from": "2025-01-01", "date_to": "2026-12-31"},
    )

    identificadores = [r["identificador_oficial"] for r in respuesta.json()["resultados"]]
    assert identificadores == ["BO-nuevo"]


def test_busqueda_respeta_el_limite_y_devuelve_metadatos_para_citar(client: TestClient, db_session: Session) -> None:
    for i in range(5):
        _crear_boletin_con_fragmento(
            db_session, sufijo=f"n{i}", fecha=datetime.date(2026, 1, 1), embedding=VECTOR_ALTO
        )

    respuesta = client.get("/v1/search", params={"q": "consulta de prueba", "limit": 2})
    cuerpo = respuesta.json()

    assert len(cuerpo["resultados"]) == 2
    primero = cuerpo["resultados"][0]
    assert {
        "fragmento_id",
        "identificador_oficial",
        "texto",
        "fecha_publicacion",
        "url_oficial",
        "similitud",
    } <= primero.keys()


def test_busqueda_sin_resultados_confiables_devuelve_lista_vacia(client: TestClient, db_session: Session) -> None:
    _crear_boletin_con_fragmento(
        db_session, sufijo="irrelevante", fecha=datetime.date(2026, 1, 1), embedding=VECTOR_BAJO
    )

    respuesta = client.get("/v1/search", params={"q": "consulta de prueba"})
    cuerpo = respuesta.json()

    assert cuerpo["resultados"] == []
    assert cuerpo["total"] == 0
