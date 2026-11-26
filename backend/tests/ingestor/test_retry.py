"""Plan 15, defect D: a document that failed is processed again when it arrives again."""
import datetime
import threading

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import (
    Documento,
    EntregaNotificacion,
    EvaluacionMatch,
    Fragmento,
    MatchingQueue,
    Suscripcion,
    Usuario,
)
from src.ingestor.contract import DocumentoNormalizado, ErrorDeProcesamiento, ingerir_documento
from src.processor.embeddings import FakeEmbeddingProvider
from tests.conftest import drain_matching_queue

TEXT = "primera parte " * 80 + "segunda parte " * 80


class Broken:
    def __init__(self, works_for: int = 0) -> None:
        self._left = works_for

    def embed_passage(self, text):
        self._left -= 1
        if self._left < 0:
            raise RuntimeError("no model")
        return FakeEmbeddingProvider().embed_passage(text)


def _document(**changes) -> DocumentoNormalizado:
    values = dict(
        fuente_clave="f", identificador_externo="d", fecha=datetime.date(2026, 1, 1), texto=TEXT,
        url_fuente="https://example.org", metadata={"a": 1}, page_starts=[(0, 3), (1120, 4)],
    )  # fmt: skip
    return DocumentoNormalizado(**{**values, **changes})


def _fail(session: Session, **changes) -> int:
    with pytest.raises(ErrorDeProcesamiento):
        ingerir_documento(session, Broken(works_for=1), _document(**changes))
    return session.scalar(select(Documento.id))


def _subscribe(session: Session) -> None:
    user = Usuario(email="a@example.org", password_hash="x")
    session.add(user)
    session.flush()
    session.add(
        Suscripcion(usuario_id=user.id, texto_busqueda="x", embedding=FakeEmbeddingProvider().embed_query(TEXT[:1000]))
    )
    session.commit()


def _count(session: Session, table) -> int:
    return session.scalar(select(func.count()).select_from(table))


def test_a_document_that_failed_once_ends_complete_and_is_matched_once(db_session: Session) -> None:
    _subscribe(db_session)
    identifier = _fail(db_session)
    drain_matching_queue(db_session)
    assert _count(db_session, EvaluacionMatch) == 0

    result = ingerir_documento(db_session, FakeEmbeddingProvider(), _document())
    assert result.documento.id == identifier and result.documento.estado == "completo"
    assert result.retried and not result.ya_existia
    assert result.fragmentos_creados == _count(db_session, Fragmento) > 1
    positions = db_session.scalars(select(Fragmento.posicion).order_by(Fragmento.posicion)).all()
    assert positions == list(range(len(positions))), "one set of fragments"

    again = ingerir_documento(db_session, FakeEmbeddingProvider(), _document())
    assert again.ya_existia and not again.retried
    drain_matching_queue(db_session)
    drain_matching_queue(db_session)
    assert _count(db_session, EvaluacionMatch) == _count(db_session, EntregaNotificacion) == 1


def test_it_may_fail_again(db_session: Session) -> None:
    identifier = _fail(db_session)
    for _ in range(2):
        with pytest.raises(ErrorDeProcesamiento):
            ingerir_documento(db_session, Broken(), _document())
    assert db_session.get(Documento, identifier).estado == "error"
    assert _count(db_session, Fragmento) == _count(db_session, MatchingQueue) == 0
    assert ingerir_documento(db_session, FakeEmbeddingProvider(), _document()).documento.estado == "completo"


def test_what_is_processed_is_the_stored_row(db_session: Session) -> None:
    _fail(db_session)
    result = ingerir_documento(
        db_session, FakeEmbeddingProvider(), _document(texto="otra cosa", metadata={"a": 2}, fecha=datetime.date(2026, 2, 2))
    )
    assert result.documento.texto == TEXT and result.documento.metadata_ == {"a": 1}
    fragments = db_session.scalars(select(Fragmento).order_by(Fragmento.posicion)).all()
    assert fragments[0].texto == TEXT[:1000] and fragments[0].fecha == datetime.date(2026, 1, 1)
    assert result.changed, "and the difference is reported"


def test_the_pages_are_known_if_the_text_is_the_same(db_session: Session) -> None:
    _fail(db_session)
    ingerir_documento(db_session, FakeEmbeddingProvider(), _document())
    assert db_session.scalars(select(Fragmento.page).order_by(Fragmento.posicion)).all()[::2] == [3, 4]


def test_the_same_text_under_another_identifier_also_retries(db_session: Session) -> None:
    identifier = _fail(db_session)
    result = ingerir_documento(db_session, FakeEmbeddingProvider(), _document(identificador_externo="copy"))
    assert result.documento.id == identifier and result.documento.estado == "completo"


def test_without_alerts_a_retry_queues_nothing(db_session: Session) -> None:
    _fail(db_session)
    ingerir_documento(db_session, FakeEmbeddingProvider(), _document(), evaluate=False)
    assert _count(db_session, MatchingQueue) == 0


@pytest.mark.parametrize("state", ["superseded", "not_searchable", "completo"])
def test_other_states_are_not_retried(db_session: Session, state: str) -> None:
    document = ingerir_documento(db_session, FakeEmbeddingProvider(), _document(), evaluate=False).documento
    document.estado = state
    db_session.commit()
    before = _count(db_session, Fragmento)
    result = ingerir_documento(db_session, Broken(), _document())
    assert result.ya_existia and not result.retried
    assert _count(db_session, Fragmento) == before and result.documento.estado == state


def test_two_retries_at_once_make_one_document(db_session: Session) -> None:
    identifier = _fail(db_session)
    db_session.commit()
    sessions = sessionmaker(bind=db_session.get_bind())
    barrier, outcomes = threading.Barrier(2, timeout=10), []

    class Slow:
        def embed_passage(self, text):
            return FakeEmbeddingProvider().embed_passage(text)

    def run() -> None:
        with sessions() as session:
            barrier.wait()
            outcomes.append(ingerir_documento(session, Slow(), _document()).retried)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert sorted(outcomes) == [False, True]
    db_session.expire_all()
    assert db_session.get(Documento, identifier).estado == "completo"
    positions = db_session.scalars(select(Fragmento.posicion).order_by(Fragmento.posicion)).all()
    assert positions == list(range(len(positions)))
    assert _count(db_session, MatchingQueue) == 1


def test_the_next_run_of_a_connector_recovers_the_document(db_session: Session) -> None:
    from src.connectors.runner import ejecutar_conector
    from src.db.models import Fuente

    source = Fuente(clave="f", nombre="f", config={})
    db_session.add(source)
    db_session.commit()

    class Connector:
        def descubrir(self, *, fuente_clave, config):
            yield _document()

    first = ejecutar_conector(db_session, Broken(), source, Connector(), {}, version_conector="v")
    second = ejecutar_conector(db_session, FakeEmbeddingProvider(), source, Connector(), {}, version_conector="v")
    third = ejecutar_conector(db_session, FakeEmbeddingProvider(), source, Connector(), {}, version_conector="v")
    assert [(r.nuevos, r.existentes, r.errores) for r in (first, second, third)] == [(0, 0, 1), (1, 0, 0), (0, 1, 0)]
