"""Plan 15, defect C: the declared filters find what was stored before."""
import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.installation import FiltroSeleccion, FuenteConfig, InstallationConfig, upsert_fuentes
from src.db.models import Documento, Fuente
from src.ingestor.contract import DocumentoNormalizado, ingerir_documento
from src.processor.embeddings import FakeEmbeddingProvider
from src.search.postgres import buscar
from src.search.results import ModoBusqueda

DECLARED = [FiltroSeleccion(clave="provincia", etiqueta="Provincia")]


def _installation(**metadata) -> InstallationConfig:
    return InstallationConfig(
        nombre="x",
        fuentes=[FuenteConfig(clave="gazette", nombre="g", metadata=metadata), FuenteConfig(clave="other", nombre="o")],
        filtros=DECLARED,
    )


def _ingest(session: Session, key: str, source: str = "gazette", **metadata) -> Documento:
    document = DocumentoNormalizado(
        source, key, datetime.date(2026, 1, 1), f"texto {key}", "https://example.org", metadata=metadata
    )
    return ingerir_documento(session, FakeEmbeddingProvider(), document).documento


def _found(session: Session, value: str) -> set[str]:
    results = buscar(
        session, FakeEmbeddingProvider(), consulta="texto", modo=ModoBusqueda.all, limite=50,
        filtros_solicitados={"provincia": value}, filtros_declarados=DECLARED,
    )  # fmt: skip
    return {r.identificador_externo for r in results}


def test_a_search_finds_new_and_previously_stored_documents(db_session: Session) -> None:
    _ingest(db_session, "before", seccion=4, jurisdiccion="provincial")
    _ingest(db_session, "elsewhere", source="other")
    assert _found(db_session, "Córdoba") == set(), "the defect"
    upsert_fuentes(db_session, _installation(provincia="Córdoba"))
    _ingest(db_session, "after")
    assert _found(db_session, "Córdoba") == {"before", "after"}
    db_session.expire_all()
    stored = db_session.scalar(select(Documento).where(Documento.identificador_externo == "before"))
    assert stored.metadata_ == {"seccion": 4, "jurisdiccion": "provincial", "provincia": "Córdoba"}


def test_a_value_of_the_document_is_kept(db_session: Session) -> None:
    _ingest(db_session, "own", provincia="San Luis")
    upsert_fuentes(db_session, _installation(provincia="Córdoba", pais="Argentina"))
    db_session.expire_all()
    assert db_session.scalar(select(Documento)).metadata_ == {"provincia": "San Luis", "pais": "Argentina"}


def test_nothing_is_written_the_second_time(db_session: Session) -> None:
    _ingest(db_session, "a")
    upsert_fuentes(db_session, _installation(provincia="Córdoba"))
    db_session.expire_all()
    before = db_session.scalar(select(Documento.changed_xid))
    upsert_fuentes(db_session, _installation(provincia="Córdoba"))
    db_session.expire_all()
    assert db_session.scalar(select(Documento.changed_xid)) == before


def test_documents_of_a_source_that_existed_without_declaration(db_session: Session) -> None:
    db_session.add(Fuente(clave="gazette", nombre="gazette", config={}))
    db_session.commit()
    _ingest(db_session, "a")
    upsert_fuentes(db_session, _installation(provincia="Córdoba"))
    assert _found(db_session, "Córdoba") == {"a"}


def test_a_subscription_with_the_filter_matches_collected_documents(db_session: Session) -> None:
    from src.db.models import EvaluacionMatch, Suscripcion, Usuario
    from tests.conftest import drain_matching_queue

    upsert_fuentes(db_session, _installation(provincia="Córdoba"))
    user = Usuario(email="a@example.org", password_hash="x")
    db_session.add(user)
    db_session.flush()
    db_session.add(
        Suscripcion(
            usuario_id=user.id, texto_busqueda="x", embedding=FakeEmbeddingProvider().embed_query("texto a"),
            filtros={"provincia": {"tipo": "seleccion", "valor": "Córdoba"}},
        )
    )  # fmt: skip
    db_session.commit()
    _ingest(db_session, "a")
    drain_matching_queue(db_session)
    assert len(db_session.scalars(select(EvaluacionMatch)).all()) == 1
