"""T007: `ejecutar_conector` — cuenta nuevos/existentes/errores, mantiene
el invariante `descubiertos = nuevos + existentes + errores` (SC-003), y
un error individual no pierde el resto de la ejecución (FR-003)."""
import datetime

import pytest
from sqlalchemy.orm import Session

from src.connectors.protocol import ErrorDescubrimiento
from src.connectors.runner import ejecutar_conector
from src.db.models import EjecucionFuente, Fuente
from src.ingestor.contract import DocumentoNormalizado
from src.processor.embeddings import FakeEmbeddingProvider


@pytest.fixture()
def fuente(db_session: Session) -> Fuente:
    f = Fuente(clave="fuente-test", nombre="Fuente de prueba", config={})
    db_session.add(f)
    db_session.flush()
    return f


class _ConectorFake:
    def __init__(self, items):
        self._items = items

    def descubrir(self, *, fuente_clave, config):
        yield from self._items


def _doc(identificador: str, texto: str | None = None) -> DocumentoNormalizado:
    if texto is None:
        texto = f"texto de prueba para {identificador}"
    return DocumentoNormalizado(
        fuente_clave="fuente-test",
        identificador_externo=identificador,
        fecha=datetime.date(2026, 1, 1),
        texto=texto,
        url_fuente=f"https://example.org/{identificador}",
    )


def test_ejecucion_cuenta_nuevos_y_mantiene_el_invariante(db_session: Session, fuente: Fuente) -> None:
    conector = _ConectorFake([_doc("a"), _doc("b"), _doc("c")])

    ejecucion = ejecutar_conector(
        db_session, FakeEmbeddingProvider(), fuente, conector, {}, version_conector="fake-v1"
    )

    assert ejecucion.estado == "completada"
    assert ejecucion.descubiertos == 3
    assert ejecucion.nuevos == 3
    assert ejecucion.existentes == 0
    assert ejecucion.errores == 0
    assert ejecucion.descubiertos == ejecucion.nuevos + ejecucion.existentes + ejecucion.errores
    assert ejecucion.fin is not None
    assert ejecucion.version_conector == "fake-v1"

    guardada = db_session.get(EjecucionFuente, ejecucion.id)
    assert guardada is not None


def test_ejecucion_cuenta_existentes_cuando_el_documento_ya_fue_ingerido(
    db_session: Session, fuente: Fuente
) -> None:
    conector = _ConectorFake([_doc("a")])
    ejecutar_conector(db_session, FakeEmbeddingProvider(), fuente, conector, {}, version_conector="fake-v1")

    segunda = ejecutar_conector(
        db_session, FakeEmbeddingProvider(), fuente, conector, {}, version_conector="fake-v1"
    )

    assert segunda.descubiertos == 1
    assert segunda.nuevos == 0
    assert segunda.existentes == 1
    assert segunda.errores == 0


def test_error_de_descubrimiento_no_pierde_el_resto_de_la_ejecucion(
    db_session: Session, fuente: Fuente
) -> None:
    conector = _ConectorFake(
        [_doc("a"), ErrorDescubrimiento(identificador_externo="b", error="PDF ilegible"), _doc("c")]
    )

    ejecucion = ejecutar_conector(
        db_session, FakeEmbeddingProvider(), fuente, conector, {}, version_conector="fake-v1"
    )

    assert ejecucion.estado == "completada"
    assert ejecucion.descubiertos == 3
    assert ejecucion.nuevos == 2
    assert ejecucion.errores == 1
    assert ejecucion.descubiertos == ejecucion.nuevos + ejecucion.existentes + ejecucion.errores
    assert ejecucion.detalle_errores == [{"identificador_externo": "b", "error": "PDF ilegible"}]


def test_error_de_ingesta_individual_no_pierde_el_resto_de_la_ejecucion(
    db_session: Session, fuente: Fuente
) -> None:
    """Un documento con texto vacío falla la validación de `ingerir_documento`,
    pero no debe tirar abajo toda la ejecución."""
    conector = _ConectorFake([_doc("a"), _doc("b", texto=""), _doc("c")])

    ejecucion = ejecutar_conector(
        db_session, FakeEmbeddingProvider(), fuente, conector, {}, version_conector="fake-v1"
    )

    assert ejecucion.descubiertos == 3
    assert ejecucion.nuevos == 2
    assert ejecucion.errores == 1
    assert ejecucion.descubiertos == ejecucion.nuevos + ejecucion.existentes + ejecucion.errores


def test_error_del_conector_completo_marca_la_ejecucion_como_fallida(
    db_session: Session, fuente: Fuente
) -> None:
    class _ConectorQueFalla:
        def descubrir(self, *, fuente_clave, config):
            raise RuntimeError("no se pudo conectar")
            yield  # pragma: no cover - hace de esto un generador

    ejecucion = ejecutar_conector(
        db_session, FakeEmbeddingProvider(), fuente, _ConectorQueFalla(), {}, version_conector="fake-v1"
    )

    assert ejecucion.estado == "fallida"
    assert ejecucion.fin is not None
    assert any("no se pudo conectar" in d["error"] for d in ejecucion.detalle_errores)
