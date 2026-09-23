"""T025: verificación del riesgo 10.6 del design spec — un filtro de
metadata muy selectivo combinado con el índice HNSW podría no encontrar un
documento que sí existe, porque el índice es aproximado.

Lo que se pudo confirmar contra la instancia real (`pgvector` 0.8.5):

- `hnsw.iterative_scan` (la mitigación de pgvector para este problema,
  disponible desde 0.8) está **apagado por defecto** (`SHOW
  hnsw.iterative_scan` devuelve `off`).
- Bajo la configuración por defecto y el sobremuestreo actual del
  endpoint (`candidatos = max(limite * 5, 50)`, ver `src/api/search.py`),
  no se pudo reproducir una pérdida de recall ni con cientos de
  fragmentos "ruido" y `hnsw.ef_search` forzado a 1: el caso adversarial
  sintético (vectores casi ortogonales entre sí) no estresa el índice
  igual que embeddings reales de alta dimensión.

Conclusión: el riesgo sigue siendo real en teoría (documentado en pgvector
y en la sección 10.6), pero no se logró reproducir con datos sintéticos
en esta etapa. Queda pendiente evaluarlo con un corpus real de mayor
volumen (Etapa 2), y activar `hnsw.iterative_scan` preventivamente si el
corpus crece más allá de lo que cubre el sobremuestreo actual.
"""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_installation_config, get_session
from src.api.main import app
from src.config.installation import FiltroSeleccion, InstallationConfig
from src.db.models import Documento, Fragmento, Fuente

DIM = 1024


def _one_hot(indice: int, dim: int = DIM) -> list[float]:
    v = [0.0] * dim
    v[indice] = 1.0
    return v


class _VectorFijoEmbeddingProvider:
    def __init__(self, vectores: dict[str, list[float]]) -> None:
        self._vectores = vectores

    def embed_query(self, texto: str) -> list[float]:
        return self._vectores[texto]

    def embed_passage(self, texto: str) -> list[float]:
        return self._vectores[texto]


def _crear(session: Session, *, sufijo: str, embedding: list[float], metadata: dict) -> None:
    fuente = session.query(Fuente).filter_by(clave="ruido").one_or_none()
    if fuente is None:
        fuente = Fuente(clave="ruido", nombre="ruido", config={})
        session.add(fuente)
        session.flush()
    documento = Documento(
        fuente_id=fuente.id,
        identificador_externo=sufijo,
        fecha=datetime.date(2026, 1, 1),
        texto="texto",
        url_fuente=f"https://example.org/{sufijo}",
        hash_contenido=f"hash-{sufijo}",
        estado="completo",
        metadata_=metadata,
    )
    session.add(documento)
    session.flush()
    session.add(
        Fragmento(documento_id=documento.id, posicion=0, texto="texto", fecha=documento.fecha, embedding=embedding)
    )
    session.flush()


def test_hnsw_iterative_scan_esta_apagado_por_defecto(db_session: Session) -> None:
    """Confirma el estado real de la mitigación del riesgo 10.6, para que
    quede como hecho verificado y no como suposición. El GUC `hnsw.*` solo
    se registra en la sesión una vez que se usa una función de la
    extensión, de ahí el cast trivial."""
    db_session.execute(text("SELECT '[1]'::vector"))
    valor = db_session.execute(text("SHOW hnsw.iterative_scan")).scalar_one()
    assert valor == "off"


@pytest.mark.slow
def test_filtro_selectivo_encuentra_el_unico_match_con_muchos_no_matches(db_session: Session) -> None:
    """Bajo la configuración por defecto de esta instalación (sin forzar
    `hnsw.iterative_scan`), un filtro selectivo con 200 documentos que no
    matchean sigue encontrando el único que sí matchea, aunque tenga la
    peor similitud vectorial posible."""
    consulta = "consulta"
    vector_consulta = _one_hot(0)
    for i in range(200):
        v = _one_hot(0)
        v[i % (DIM - 2) + 1] = 0.2
        _crear(db_session, sufijo=f"ruido-{i}", embedding=v, metadata={"municipio": "Otro"})
    _crear(db_session, sufijo="objetivo", embedding=_one_hot(DIM - 1), metadata={"municipio": "Carlos Paz"})

    installation = InstallationConfig(
        nombre="test", filtros=[FiltroSeleccion(clave="municipio", etiqueta="Municipio")]
    )

    def _get_session_override():
        yield db_session

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[get_embedder] = lambda: _VectorFijoEmbeddingProvider({consulta: vector_consulta})
    app.dependency_overrides[get_installation_config] = lambda: installation
    try:
        respuesta = TestClient(app).get(
            "/v1/search",
            params={"q": consulta, "mode": "all", "limit": 5, "filtro.municipio": "Carlos Paz"},
        )
    finally:
        app.dependency_overrides.clear()

    identificadores = [r["identificador_externo"] for r in respuesta.json()["resultados"]]
    assert identificadores == ["objetivo"]
