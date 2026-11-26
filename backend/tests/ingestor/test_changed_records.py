"""Plan 15, defects F and G: a record that arrives again is compared with what is stored."""
import datetime
import logging

import pytest
from sqlalchemy.orm import Session

from src.db.models import Documento, Fuente, MatchingQueue
from src.ingestor import contract
from src.ingestor.changes import differences
from src.ingestor.contract import DocumentoNormalizado, ingerir_documento
from src.processor.embeddings import FakeEmbeddingProvider


@pytest.mark.parametrize(
    ("stored", "incoming"),
    [
        ({"a": 1, "b": 2}, {"b": 2, "a": 1}),
        ({"monto": 100}, {"monto": 100.0}),
        ({"monto": 100.0}, {"monto": "100"}),
        ({"monto": "100.00"}, {"monto": 100}),
        ({"a": "Ministerio  de Salud "}, {"a": "Ministerio de Salud"}),
        ({"a": "Direcci\u00f3n"}, {"a": "Direccio\u0301n"}),
        ({"a": {"x": 1, "y": [1, 2]}}, {"a": {"y": [1.0, 2], "x": 1}}),
        ({"a": None}, {"a": None}),
        ({}, {"new": 1}),
    ],
)
def test_what_is_not_a_change(stored: dict, incoming: dict) -> None:
    assert differences("texto", stored, "texto", incoming) == []


@pytest.mark.parametrize(
    ("stored", "incoming", "keys"),
    [
        ({"monto": 100}, {"monto": 101}, ["monto"]),
        ({"monto": 100}, {"monto": 100.01}, ["monto"]),
        ({"a": "x"}, {"a": "y"}, ["a"]),
        ({"a": "x"}, {"a": None}, ["a"]),
        ({"a": "x", "b": 1}, {"b": 1}, ["a"]),
        ({"a": [1, 2]}, {"a": [2, 1]}, ["a"]),
        ({"a": "0088"}, {"a": "88"}, ["a"]),
        ({"a": True}, {"a": 1}, ["a"]),
        ({"b": 1, "a": 1}, {"b": 2, "a": 2}, ["a", "b"]),
    ],
)
def test_what_is_a_change(stored: dict, incoming: dict, keys: list) -> None:
    assert differences("texto", stored, "texto", incoming) == keys


@pytest.mark.parametrize("text", ["texto largo", " texto\n  largo ", "texto\tlargo"])
def test_spacing_of_the_text_is_not_a_change(text: str) -> None:
    assert differences("texto largo", {}, text, {}) == []


def test_another_text_is_a_change() -> None:
    assert differences("apertura el 5", {}, "apertura el 6", {}) == ["texto"]


def _ingest(session: Session, text: str = "texto", **metadata):
    document = DocumentoNormalizado(
        "f", "tender-1", datetime.date(2026, 1, 1), text, "https://example.org", metadata=metadata
    )
    return ingerir_documento(session, FakeEmbeddingProvider(), document)


def test_a_change_is_reported_and_the_stored_document_is_not_overwritten(db_session: Session, caplog, monkeypatch) -> None:
    monkeypatch.setattr(contract.logger, "disabled", False)  # the migrations of the fixture disable it
    _ingest(db_session, monto=10, organismo="A")
    with caplog.at_level(logging.WARNING, logger="contextcrawl.ingest"):  # what a service shows by default
        result = _ingest(db_session, "otro texto", monto=12, organismo="A")
    assert result.changed and result.ya_existia
    db_session.expire_all()
    stored = db_session.get(Documento, result.documento.id)
    assert stored.texto == "texto" and stored.metadata_ == {"monto": 10, "organismo": "A"}
    (message,) = [r.getMessage() for r in caplog.records]
    assert "tender-1" in message and "monto" in message and "texto" in message
    assert "otro texto" not in message and "12" not in message, "which fields, not their content"


def test_an_unchanged_record_is_silent(db_session: Session, caplog, monkeypatch) -> None:
    monkeypatch.setattr(contract.logger, "disabled", False)
    _ingest(db_session, monto=10)
    with caplog.at_level(logging.INFO, logger="contextcrawl.ingest"):
        assert not _ingest(db_session, monto=10.0).changed
    assert caplog.records == []


def test_keys_it_did_not_have_are_added(db_session: Session) -> None:
    first = _ingest(db_session, monto=10)
    result = _ingest(db_session, monto=10, opening_date="2026-02-01T10:00:00")
    assert not result.changed
    db_session.expire_all()
    assert db_session.get(Documento, first.documento.id).metadata_ == {
        "monto": 10,
        "opening_date": "2026-02-01T10:00:00",
    }
    assert db_session.query(MatchingQueue).count() == 1, "it is not matched again"


def test_new_keys_are_added_even_if_others_changed(db_session: Session) -> None:
    _ingest(db_session, monto=10)
    result = _ingest(db_session, monto=12, extra="x")
    db_session.expire_all()
    assert result.changed and db_session.get(Documento, result.documento.id).metadata_ == {"monto": 10, "extra": "x"}


def test_fixed_metadata_of_the_source_is_not_a_difference(db_session: Session) -> None:
    db_session.add(Fuente(clave="f", nombre="f", config={"metadata": {"provincia": "Córdoba"}}))
    db_session.commit()
    assert _ingest(db_session, monto=10).documento.metadata_ == {"monto": 10, "provincia": "Córdoba"}
    assert not _ingest(db_session, monto=10).changed


def test_the_same_text_under_another_identifier_is_a_duplicate_and_not_a_change(db_session: Session) -> None:
    _ingest(db_session, monto=10)
    copy = DocumentoNormalizado(
        "f", "other", datetime.date(2026, 1, 1), "texto", "https://example.org", metadata={"monto": 99, "extra": 1}
    )
    result = ingerir_documento(db_session, FakeEmbeddingProvider(), copy)
    assert result.ya_existia and not result.changed
    db_session.expire_all()
    assert db_session.get(Documento, result.documento.id).metadata_ == {"monto": 10}


def test_a_gazette_issue_collected_twice_has_no_changes(db_session: Session) -> None:
    """And neither has one whose notices were split from the saved text."""
    from pathlib import Path

    from src.connectors.boletin_cba.connector import ConectorBoletinCba
    from src.connectors.bop_cordoba.pdf import extraer_texto_pdf
    from src.connectors.runner import ejecutar_conector
    from src.ingestor.resegment import resegment_source

    pdf = Path(__file__).resolve().parents[1] / "fixtures" / "boletin_cba" / "4_Secc_sample.pdf"
    source = Fuente(clave="g", nombre="g", config={})
    db_session.add(source)
    db_session.commit()
    section = DocumentoNormalizado(
        "g", "4_Secc_240926", datetime.date(2026, 9, 24), extraer_texto_pdf(pdf.read_bytes()), pdf.as_uri()
    )
    ingerir_documento(db_session, FakeEmbeddingProvider(), section, evaluate=False)
    resegment_source(db_session, FakeEmbeddingProvider(), source, ConectorBoletinCba())
    config = {"url_template": pdf.as_uri(), "secciones": [4], "fecha": "2026-09-24"}
    run = ejecutar_conector(
        db_session, FakeEmbeddingProvider(), source, ConectorBoletinCba(), config, version_conector="v"
    )
    assert (run.nuevos, run.existentes, run.changed, run.errores) == (0, 36, 0, 0)
