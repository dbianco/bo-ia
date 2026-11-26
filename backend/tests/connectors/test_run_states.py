"""Plan 15, defects E and G: what a run says about itself."""
import datetime

import pytest
from sqlalchemy.orm import Session

from src.connectors.protocol import ErrorDescubrimiento
from src.connectors.runner import ejecutar_conector
from src.db.models import Fuente
from src.ingestor.contract import DocumentoNormalizado
from src.processor.embeddings import FakeEmbeddingProvider


@pytest.fixture()
def run(db_session: Session):
    source = Fuente(clave="f", nombre="f", config={})
    db_session.add(source)
    db_session.commit()

    def execute(*items, embedder=None):
        class Connector:
            def descubrir(self, *, fuente_clave, config):
                for item in items:
                    if isinstance(item, Exception):
                        raise item
                    yield item

        return ejecutar_conector(
            db_session, embedder or FakeEmbeddingProvider(), source, Connector(), {}, version_conector="v"
        )

    return execute


def doc(key: str, text: str | None = None, **metadata) -> DocumentoNormalizado:
    return DocumentoNormalizado(
        "f", key, datetime.date(2026, 1, 1), text or f"texto {key}", "https://example.org", metadata=metadata
    )


ERROR = ErrorDescubrimiento("x", "PDF ilegible")


def test_a_run_in_which_every_item_failed_is_failed(run) -> None:
    result = run(ERROR, ERROR)
    assert result.estado == "fallida" and (result.descubiertos, result.errores) == (2, 2)


def test_a_run_in_which_no_document_could_be_processed_is_failed(run) -> None:
    class Broken:
        def embed_passage(self, text):
            raise RuntimeError("no model")

    assert run(doc("a"), doc("b"), embedder=Broken()).estado == "fallida"


def test_a_run_with_some_failures_is_partial(run) -> None:
    assert run(doc("a"), ERROR).estado == "partial"
    assert run(doc("a"), ERROR).estado == "partial", "an item that was already there counts as processed"


def test_a_run_without_failures_is_complete(run) -> None:
    assert run(doc("a")).estado == "completada"
    assert run(doc("a")).estado == "completada"


def test_a_run_that_found_nothing_is_complete(run) -> None:
    """Nothing was published: the source works."""
    assert run().estado == "completada"


def test_a_connector_that_breaks_is_failed_even_after_some_items(run) -> None:
    result = run(doc("a"), RuntimeError("connection lost"))
    assert result.estado == "fallida" and result.nuevos == 1


def test_changed_records_are_counted_apart(run) -> None:
    run(doc("a", monto=10), doc("b"), doc("c"))
    result = run(doc("a", monto=12), doc("b", "otro texto"), doc("c"), doc("d"))
    assert (result.nuevos, result.existentes, result.changed) == (1, 3, 2)
    assert result.descubiertos == result.nuevos + result.existentes + result.errores
    assert result.estado == "completada"
    assert run(doc("c")).changed == 0


def test_the_api_shows_the_changed_count(db_session: Session, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from src.api import deps, fuentes
    from src.api.main import app
    from src.config.installation import ConectorConfig, FuenteConfig, InstallationConfig

    class Connector:
        def descubrir(self, *, fuente_clave, config):
            yield doc("a")

    db_session.add(Fuente(clave="f", nombre="f", config={}))
    db_session.commit()
    monkeypatch.setitem(fuentes.CONECTORES, "fake", Connector)
    monkeypatch.setenv("OPERATOR_TOKEN", "t")
    app.dependency_overrides[deps.get_session] = lambda: iter([db_session]).__next__()
    app.dependency_overrides[deps.get_embedder] = lambda: FakeEmbeddingProvider()
    app.dependency_overrides[deps.get_installation_config] = lambda: InstallationConfig(
        nombre="x", fuentes=[FuenteConfig(clave="f", nombre="f", conector=ConectorConfig(tipo="fake", frecuencia_minutos=1))]
    )
    try:
        body = TestClient(app).post("/v1/fuentes/f/ejecutar", headers={"Authorization": "Bearer t"}).json()
    finally:
        app.dependency_overrides.clear()
    assert body["changed"] == 0 and body["nuevos"] == 1
