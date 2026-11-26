"""Plan 7: notices through the single ingestion path."""
import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Documento, EvaluacionMatch, Fragmento, Fuente, Suscripcion, Usuario
from src.ingestor.contract import DocumentoNormalizado, ingerir_documento
from src.ingestor.fragmenter import fragment_spans, fragmentar_texto
from src.processor.hashed_embeddings import HashedEmbeddingProvider

DAY = datetime.date(2026, 9, 24)


@pytest.fixture(scope="module")
def embedder():
    return HashedEmbeddingProvider()


def _notice(**changes) -> DocumentoNormalizado:
    values = dict(
        fuente_clave="cordoba-provincial",
        identificador_externo="4_Secc_240926_N1",
        fecha=DAY,
        texto="MINISTERIO DE SALUD\nLicitación pública.\n3 días - Nº 1 - s/c - 26/9/2026 - BOE",
        url_fuente="https://example.org/4.pdf#page=3",
        notice_number="1",
        issue="4_Secc_240926",
        page_starts=[(0, 3)],
    )
    return DocumentoNormalizado(**{**values, **changes})


def _subscribe(session: Session, embedder, text: str, filters: dict | None = None) -> Suscripcion:
    user = Usuario(email="a@example.org", password_hash="x")
    session.add(user)
    session.flush()
    subscription = Suscripcion(
        usuario_id=user.id, texto_busqueda=text, embedding=embedder.embed_query(text), filtros=filters or {}
    )
    session.add(subscription)
    session.commit()
    return subscription


def test_fragment_spans_locate_each_fragment_in_the_text() -> None:
    text = "  \n" + "palabra " * 400 + "\n"
    spans = fragment_spans(text, tamano=500, solapamiento=100)
    assert [text[a:b] for a, b in spans] == fragmentar_texto(text, tamano=500, solapamiento=100)


def test_stores_number_issue_and_pages(db_session: Session, embedder) -> None:
    document = ingerir_documento(db_session, embedder, _notice(page_starts=[(0, 3), (30, 4)])).documento
    assert (document.notice_number, document.issue) == ("1", "4_Secc_240926")
    assert (document.first_page, document.last_page) == (3, 4)


def test_each_fragment_records_the_page_where_it_starts(db_session: Session, embedder) -> None:
    text = "a" * 900 + "\n" + "b" * 900 + "\n" + "c" * 300
    document = ingerir_documento(db_session, embedder, _notice(texto=text, page_starts=[(0, 7), (901, 8), (1802, 9)])).documento
    fragments = db_session.scalars(
        select(Fragmento).where(Fragmento.documento_id == document.id).order_by(Fragmento.posicion)
    ).all()
    # 1000 characters with an overlap of 200: they start at 0, 800 and 1600.
    assert [f.page for f in fragments] == [7, 7, 8]


def test_a_document_without_pages_has_none(db_session: Session, embedder) -> None:
    document = ingerir_documento(db_session, embedder, _notice(page_starts=[], notice_number=None, issue=None)).documento
    assert document.first_page is None and document.last_page is None and document.issue is None
    assert db_session.scalars(select(Fragmento.page)).all() == [None]


def test_identical_notices_on_different_days_are_all_kept(db_session: Session, embedder) -> None:
    """The same notice runs on consecutive days, with the same number and text."""
    for offset in range(3):
        day = DAY + datetime.timedelta(days=offset)
        result = ingerir_documento(
            db_session, embedder, _notice(fecha=day, identificador_externo=f"4_Secc_{day:%d%m%y}_N1")
        )
        assert not result.ya_existia
    dates = db_session.scalars(select(Documento.fecha).order_by(Documento.fecha)).all()
    assert dates == [DAY + datetime.timedelta(days=i) for i in range(3)]


def test_the_same_text_on_the_same_day_is_still_a_duplicate(db_session: Session, embedder) -> None:
    ingerir_documento(db_session, embedder, _notice())
    again = ingerir_documento(db_session, embedder, _notice(identificador_externo="other", fuente_clave="other"))
    assert again.ya_existia


def test_a_document_that_is_not_searchable_is_stored_without_fragments_or_matches(db_session: Session, embedder) -> None:
    _subscribe(db_session, embedder, "licitaciones")
    result = ingerir_documento(db_session, embedder, _notice(texto="Licitaciones ..... Pag. 1", searchable=False))
    assert result.documento.estado == "not_searchable"
    assert result.fragmentos_creados == 0
    assert db_session.scalars(select(Fragmento)).all() == []
    assert db_session.scalars(select(EvaluacionMatch)).all() == []
    assert ingerir_documento(db_session, embedder, _notice(searchable=False)).ya_existia


def test_two_notices_of_one_issue_give_two_alerts(db_session: Session, embedder) -> None:
    """Before plan 7 a subscriber got at most one alert per section and day."""
    _subscribe(db_session, embedder, "licitación pública ministerio")
    for number in ("1", "2"):
        ingerir_documento(
            db_session,
            embedder,
            _notice(
                identificador_externo=f"N{number}", notice_number=number, texto=f"Licitación pública ministerio {number}"
            ),
        )
    assert len(db_session.scalars(select(EvaluacionMatch)).all()) == 2


def test_ingestion_without_alerts(db_session: Session, embedder) -> None:
    _subscribe(db_session, embedder, "licitación pública ministerio")
    ingerir_documento(db_session, embedder, _notice(texto="Licitación pública ministerio"), evaluate=False)
    assert db_session.scalars(select(EvaluacionMatch)).all() == []
    assert db_session.scalars(select(Fragmento)).all()


def test_fixed_metadata_of_the_source_is_added_to_every_document(db_session: Session, embedder) -> None:
    db_session.add(Fuente(clave="cordoba-provincial", nombre="x", config={"metadata": {"provincia": "Córdoba"}}))
    db_session.commit()
    subscription = _subscribe(
        db_session, embedder, "licitación pública", {"provincia": {"tipo": "seleccion", "valor": "Córdoba"}}
    )
    document = ingerir_documento(
        db_session, embedder, _notice(texto="licitación pública", metadata={"seccion": 4})
    ).documento
    assert document.metadata_ == {"provincia": "Córdoba", "seccion": 4}
    match = db_session.scalars(select(EvaluacionMatch)).one()
    assert match.suscripcion_id == subscription.id


def test_a_value_of_the_document_wins_over_the_source(db_session: Session, embedder) -> None:
    db_session.add(Fuente(clave="cordoba-provincial", nombre="x", config={"metadata": {"provincia": "Córdoba"}}))
    db_session.commit()
    document = ingerir_documento(db_session, embedder, _notice(metadata={"provincia": "San Luis"})).documento
    assert document.metadata_["provincia"] == "San Luis"
