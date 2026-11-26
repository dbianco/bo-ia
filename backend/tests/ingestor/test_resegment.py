"""Plan 7: re-segmentation of documents stored as whole sections."""
import datetime
import re
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.search import ModoBusqueda, buscar
from src.commands.resegment import main
from src.connectors.boletin_cba.connector import ConectorBoletinCba
from src.connectors.bop_cordoba.pdf import extraer_texto_pdf
from src.db.models import Documento, EvaluacionMatch, Fragmento, Fuente, Suscripcion, Usuario, Valoracion
from src.ingestor.contract import DocumentoNormalizado, ingerir_documento
from src.ingestor.resegment import resegment_source
from src.processor.hashed_embeddings import HashedEmbeddingProvider
from src.synthetic.issues import generate_issue

PDF = Path(__file__).resolve().parents[1] / "fixtures" / "boletin_cba" / "4_Secc_sample.pdf"
DAY = datetime.date(2026, 9, 24)
CONNECTOR = ConectorBoletinCba()
CONFIG = {"url_template": PDF.as_uri()}


@pytest.fixture(scope="module")
def embedder():
    return HashedEmbeddingProvider()


@pytest.fixture()
def source(db_session: Session) -> Fuente:
    fuente = Fuente(clave="cordoba-provincial", nombre="x", config={"metadata": {"provincia": "Córdoba"}})
    db_session.add(fuente)
    db_session.commit()
    return fuente


def _store(session: Session, embedder, text: str | None = None, identifier: str = "4_Secc_240926", **changes):
    """A whole section, as the connector stored it before plan 7."""
    values = dict(
        fuente_clave="cordoba-provincial",
        identificador_externo=identifier,
        fecha=DAY,
        texto=text if text is not None else extraer_texto_pdf(PDF.read_bytes()),
        url_fuente=PDF.as_uri(),
        metadata={"jurisdiccion": "provincial", "seccion": 4},
    )
    return ingerir_documento(session, embedder, DocumentoNormalizado(**{**values, **changes})).documento


def _notices(session: Session) -> list[Documento]:
    return list(session.scalars(select(Documento).where(Documento.notice_number.is_not(None)).order_by(Documento.id)))


def test_a_stored_section_becomes_notices_without_pages(db_session: Session, embedder, source) -> None:
    section = _store(db_session, embedder)
    summary = resegment_source(db_session, embedder, source, CONNECTOR)
    assert (summary.sections, summary.notices, summary.unsegmented, summary.failed) == (1, 35, 0, 0)
    notices = _notices(db_session)
    assert len(notices) == 35
    assert all(n.first_page is None and n.issue == "4_Secc_240926" for n in notices)
    assert all(n.url_fuente == PDF.as_uri() for n in notices)
    assert all(n.metadata_["provincia"] == "Córdoba" for n in notices)
    db_session.refresh(section)
    assert section.estado == "superseded"


def test_the_notices_are_the_ones_the_connector_produces(db_session: Session, embedder, source) -> None:
    """Same identifiers and same text, running headers removed, so that a later
    run of the connector for that day finds them and adds nothing."""
    _store(db_session, embedder)
    resegment_source(db_session, embedder, source, CONNECTOR)
    config = {"url_template": PDF.as_uri(), "secciones": [4], "fecha": "2026-09-24"}
    expected = {
        d.identificador_externo: d.texto.strip()
        for d in CONNECTOR.descubrir(fuente_clave="cordoba-provincial", config=config)
    }
    stored = {
        d.identificador_externo: d.texto.strip()
        for d in db_session.scalars(select(Documento).where(Documento.estado != "superseded"))
    }
    assert stored == expected


def test_with_the_pdf_downloaded_again_the_notices_have_pages(db_session: Session, embedder, source) -> None:
    _store(db_session, embedder)
    summary = resegment_source(db_session, embedder, source, CONNECTOR, config=CONFIG, refetch=True)
    assert summary.notices == 35 and summary.refetch_failed == 0
    notice = next(n for n in _notices(db_session) if n.notice_number == "688769")
    assert (notice.first_page, notice.last_page) == (4, 5)
    assert notice.url_fuente.endswith("#page=4")


def test_if_the_pdf_is_gone_the_saved_text_is_used(db_session: Session, embedder, source) -> None:
    _store(db_session, embedder)
    gone = {"url_template": "file:///no/such/file.pdf"}
    summary = resegment_source(db_session, embedder, source, CONNECTOR, config=gone, refetch=True)
    assert summary.refetch_failed == 1 and summary.notices == 35


def test_the_address_to_download_is_the_configured_one(db_session: Session, embedder, source, tmp_path) -> None:
    """The stored one may come from anyone who can post a document, and would be
    handed to curl: a local file, an internal address or a command line option."""
    secret, written = tmp_path / "secret", tmp_path / "written"
    secret.write_text("secret")
    for i, url in enumerate((secret.as_uri(), f"-o{written}")):
        _store(db_session, embedder, identifier=f"4_Secc_25092{i}", url_fuente=url, fecha=datetime.date(2026, 9, 20 + i))
    summary = resegment_source(db_session, embedder, source, CONNECTOR, config=CONFIG, refetch=True)
    assert summary.refetch_failed == 0 and summary.notices == 70
    assert not written.exists()
    assert {n.url_fuente.partition("#")[0] for n in _notices(db_session)} == {PDF.as_uri()}


def test_without_a_configured_address_the_saved_text_is_used(db_session: Session, embedder, source) -> None:
    _store(db_session, embedder)
    summary = resegment_source(db_session, embedder, source, CONNECTOR, refetch=True)
    assert summary.refetch_failed == 1 and summary.notices == 35


def test_the_replaced_section_is_not_found_any_more(db_session: Session, embedder, source, monkeypatch) -> None:
    monkeypatch.setenv("SIMILARITY_THRESHOLD", "0.0")
    section = _store(db_session, embedder)
    resegment_source(db_session, embedder, source, CONNECTOR)
    for mode in ModoBusqueda:
        results = buscar(db_session, embedder, consulta="licitación ministerio", limite=50, modo=mode)
        assert results and section.id not in {r.documento_id for r in results}


def test_old_notices_raise_no_alerts_and_history_is_kept(db_session: Session, embedder, source, monkeypatch) -> None:
    monkeypatch.setenv("SIMILARITY_THRESHOLD", "0.05")
    user = Usuario(email="a@example.org", password_hash="x")
    db_session.add(user)
    db_session.flush()
    text = "licitación pública ministerio"
    db_session.add(Suscripcion(usuario_id=user.id, texto_busqueda=text, embedding=embedder.embed_query(text)))
    db_session.commit()
    section = _store(db_session, embedder)
    fragment = db_session.scalars(select(Fragmento).where(Fragmento.documento_id == section.id)).first()
    db_session.add(Valoracion(fragmento_id=fragment.id, consulta="x", valor="positivo"))
    db_session.commit()
    assert len(db_session.scalars(select(EvaluacionMatch)).all()) == 1

    resegment_source(db_session, embedder, source, CONNECTOR)
    matches = db_session.scalars(select(EvaluacionMatch)).all()
    assert [m.documento_id for m in matches] == [section.id]
    assert len(db_session.scalars(select(Valoracion)).all()) == 1


def test_running_it_twice_changes_nothing(db_session: Session, embedder, source) -> None:
    _store(db_session, embedder)
    resegment_source(db_session, embedder, source, CONNECTOR)
    before = db_session.scalars(select(Documento.id).order_by(Documento.id)).all()
    summary = resegment_source(db_session, embedder, source, CONNECTOR)
    assert (summary.sections, summary.notices) == (0, 0)
    assert db_session.scalars(select(Documento.id).order_by(Documento.id)).all() == before


def test_dry_run_only_counts(db_session: Session, embedder, source) -> None:
    section = _store(db_session, embedder)
    summary = resegment_source(db_session, embedder, source, CONNECTOR, dry_run=True)
    assert (summary.sections, summary.notices) == (1, 35)
    db_session.refresh(section)
    assert section.estado == "completo" and _notices(db_session) == []


def test_a_section_that_cannot_be_split_stays_as_it_is(db_session: Session, embedder, source) -> None:
    section = _store(db_session, embedder, text="DECRETO 1\nVisto.", identifier="1_Secc_240926", metadata={"seccion": 1})
    summary = resegment_source(db_session, embedder, source, CONNECTOR)
    assert (summary.sections, summary.notices, summary.unsegmented) == (1, 0, 1)
    db_session.refresh(section)
    assert section.estado == "completo"
    assert section.issue == "1_Secc_240926"  # now explicit: part of an issue, without notices
    assert resegment_source(db_session, embedder, source, CONNECTOR).sections == 0


def test_a_failure_keeps_the_section_and_can_be_retried(db_session: Session, embedder, source) -> None:
    section = _store(db_session, embedder)

    class FailsOnce:
        calls = 0

        def embed_passage(self, text):
            FailsOnce.calls += 1
            if FailsOnce.calls == 5:
                raise RuntimeError("out of memory")
            return embedder.embed_passage(text)

        embed_query = embed_passage

    summary = resegment_source(db_session, FailsOnce(), source, CONNECTOR)
    assert summary.failed == 1
    db_session.refresh(section)
    assert section.estado == "completo", "still searchable: nothing replaced it yet"
    summary = resegment_source(db_session, embedder, source, CONNECTOR)
    assert summary.failed == 0
    db_session.refresh(section)
    assert section.estado == "superseded"
    assert all(n.estado == "completo" for n in _notices(db_session))
    assert len(_notices(db_session)) == 35


def test_documents_of_other_kinds_are_left_alone(db_session: Session, embedder, source) -> None:
    other = _store(db_session, embedder, text="Decreto\n1 día - Nº 5 - s/c - 24/9/2026 - BOE", identifier="BO-DEMO-0001")
    assert resegment_source(db_session, embedder, source, CONNECTOR).sections == 0
    db_session.refresh(other)
    assert other.estado == "completo"


def test_stored_documents_get_the_fixed_metadata_of_the_source(db_session: Session, embedder, source) -> None:
    source.config = {}
    db_session.commit()
    plain = _store(db_session, embedder, text="texto", identifier="BO-1", metadata={"provincia": "San Luis"})
    bare = _store(db_session, embedder, text="otro texto", identifier="BO-2", metadata={})
    source.config = {"metadata": {"provincia": "Córdoba"}}
    db_session.commit()
    summary = resegment_source(db_session, embedder, source, CONNECTOR)
    db_session.refresh(plain)
    db_session.refresh(bare)
    assert plain.metadata_["provincia"] == "San Luis" and bare.metadata_["provincia"] == "Córdoba"
    assert summary.metadata_filled == 1


@pytest.mark.parametrize("seed", range(8))
def test_headers_are_removed_from_the_saved_text_of_generated_issues(db_session, embedder, source, seed) -> None:
    issue = generate_issue(3000 + seed, notices=40, quotes=0.0)
    documents = CONNECTOR.resegment(
        fuente_clave="cordoba-provincial",
        identifier=f"4_Secc_{issue.date:%d%m%y}",
        issue_date=issue.date,
        text="\n".join(issue.pages),
        url="https://example.org/4.pdf",
        refetch_config=None,
    )
    notices = [d for d in documents if d.notice_number]
    assert [d.notice_number for d in notices] == [n.number for n in issue.notices]
    assert [d.texto.strip() for d in notices] == [n.text for n in issue.notices]
    assert not any(d.page_starts for d in documents)


def test_command_line(db_session: Session, embedder, source, test_database_url, tmp_path, monkeypatch, capsys) -> None:
    _store(db_session, embedder)
    config = tmp_path / "installation.yaml"
    config.write_text(
        "nombre: x\nfuentes:\n  - clave: cordoba-provincial\n    nombre: x\n    metadata: {provincia: Córdoba}\n"
        "    conector: {tipo: boletin-cba-pdf-diario, frecuencia_minutos: 1, config: {}}\n"
        "  - {clave: manual, nombre: manual}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INSTALLATION_CONFIG", str(config))
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hashed")
    main(["--source", "cordoba-provincial", "--dry-run"])
    assert re.search(r"35 notices", capsys.readouterr().out)
    main(["--source", "cordoba-provincial"])
    assert len(_notices(db_session)) == 35
    for wrong in ("manual", "unknown"):
        with pytest.raises(SystemExit):
            main(["--source", wrong])


