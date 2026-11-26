"""Plan 4: the engine behind the search interface, built from PostgreSQL and kept
current with it."""
import datetime
import threading
import time

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from src.api import deps
from src.api.search import ModoBusqueda
from src.db.models import SUPERSEDED, Documento, Fragmento
from src.engine.backend import EngineBackend, PostgresBackend, backend_from_environment
from src.ingestor.contract import ingerir_documento
from src.processor.hashed_embeddings import HashedEmbeddingProvider
from src.synthetic.corpus import CorpusConfig, generate_corpus
from tests.matching.conftest import embedder, ingest  # noqa: F401

THRESHOLD = "0.2"


@pytest.fixture(autouse=True)
def threshold(monkeypatch) -> None:
    monkeypatch.setenv("SIMILARITY_THRESHOLD", THRESHOLD)


def _found(backend, session: Session, embedder, query: str = "texto", mode="semantic", **options) -> list[int]:  # noqa: F811
    options.setdefault("limite", 50)
    results = backend.search(session, embedder, consulta=query, modo=ModoBusqueda(mode), **options)
    return [r.documento_id for r in results]


def test_new_documents_are_found_at_once(db_session, embedder, ingest) -> None:  # noqa: F811
    backend = EngineBackend()
    assert _found(backend, db_session, embedder) == []
    first = ingest()
    assert _found(backend, db_session, embedder) == [first.id]
    second = ingest("v:0.8")
    assert _found(backend, db_session, embedder) == [first.id, second.id]


def test_what_happens_to_a_document_is_seen(db_session, embedder, ingest) -> None:  # noqa: F811
    from src.config.installation import FiltroSeleccion

    declared = [FiltroSeleccion(clave="a", etiqueta="A")]
    backend = EngineBackend()
    kept, replaced, deleted = ingest(metadata={"a": "x"}), ingest(), ingest()
    kept_id = kept.id
    assert len(_found(backend, db_session, embedder)) == 3

    replaced.estado = SUPERSEDED
    db_session.execute(update(Fragmento).where(Fragmento.documento_id == replaced.id).values(embedding=None))
    db_session.delete(deleted)
    db_session.commit()
    for mode in ("semantic", "hybrid", "all"):
        assert _found(backend, db_session, embedder, mode=mode) == [kept_id]

    def filtered(value: str) -> list[int]:
        return _found(backend, db_session, embedder, filtros_solicitados={"a": value}, filtros_declarados=declared)

    assert filtered("x") == [kept_id] and filtered("y") == []
    kept.metadata_ = {"a": "y"}
    db_session.commit()
    assert filtered("y") == [kept_id] and filtered("x") == []


def test_a_fragment_added_or_changed_after_its_document(db_session, embedder, ingest) -> None:  # noqa: F811
    backend = EngineBackend()
    document = ingest("v:0.5")
    assert _found(backend, db_session, embedder) == [document.id]
    db_session.add(
        Fragmento(
            documento_id=document.id, posicion=7, texto="hipopótamo", fecha=document.fecha,
            embedding=embedder.embed_passage("texto"),
        )
    )  # fmt: skip
    db_session.commit()
    assert len(_found(backend, db_session, embedder)) == 2
    assert len(_found(backend, db_session, embedder, "hipopótamos", mode="hybrid")) == 2
    fragment = db_session.scalars(select(Fragmento).where(Fragmento.posicion == 7)).one()
    fragment.embedding = [-x for x in embedder.embed_passage("texto")]
    db_session.commit()
    assert len(_found(backend, db_session, embedder)) == 1


def test_a_deleted_document_does_not_take_the_place_of_another(db_session, embedder, ingest) -> None:  # noqa: F811
    backend = EngineBackend()
    best, second = ingest("v:0.9"), ingest("v:0.8")
    second_id = second.id
    assert _found(backend, db_session, embedder, limite=1) == [best.id]
    db_session.delete(best)
    db_session.commit()
    assert _found(backend, db_session, embedder, limite=1) == [second_id]


def test_a_document_committed_late_is_not_missed(db_session, embedder, ingest) -> None:  # noqa: F811
    backend = EngineBackend()
    hidden = ingest()
    hidden_id = hidden.id
    hidden.estado = SUPERSEDED
    db_session.commit()
    other = sessionmaker(bind=db_session.get_bind())()
    try:
        other.get(Documento, hidden_id).estado = "completo"
        other.flush()
        newer = ingest("v:0.9")
        assert _found(backend, db_session, embedder) == [newer.id]
        db_session.commit()
        other.commit()
        assert _found(backend, db_session, embedder) == [hidden_id, newer.id]
    finally:
        other.close()


def test_only_what_changed_is_read(db_session, embedder, ingest) -> None:  # noqa: F811
    backend = EngineBackend()
    for _ in range(4):
        ingest()
    assert backend.sync(db_session) == 4
    assert backend.sync(db_session) == 0
    ingest()
    assert 1 <= backend.sync(db_session) <= 2


def test_both_give_the_same_semantic_results(db_session) -> None:
    corpus = generate_corpus(CorpusConfig(seed=2, documents=120, queries=20))
    provider = HashedEmbeddingProvider(synonyms=corpus.synonym_table(0.8))
    for document in corpus.documents:
        ingerir_documento(db_session, provider, document, evaluate=False)
    engine, postgres = EngineBackend(), PostgresBackend()
    for query in corpus.truth.queries:
        options = {
            "consulta": query.text,
            "filtros_solicitados": query.filters,
            "filtros_declarados": list(corpus.profile.filters),
            "fecha_desde": datetime.date(2026, 2, 1),
            "limite": 20,
        }
        a = engine.search(db_session, provider, modo=ModoBusqueda.semantic, **options)
        b = postgres.search(db_session, provider, modo=ModoBusqueda.semantic, **options)
        assert [r.similitud for r in a] == pytest.approx([r.similitud for r in b], abs=2e-4)
        # Republished notices tie: which of them is the last one of the list is not defined.
        last = min([r.similitud for r in b], default=0) + 2e-4
        assert {r.fragmento_id for r in a if r.similitud > last} == {r.fragmento_id for r in b if r.similitud > last}
        options["limite"] = 1000
        for mode in (ModoBusqueda.hybrid, ModoBusqueda.all):
            a = {r.fragmento_id for r in engine.search(db_session, provider, modo=mode, **options)}
            b = {r.fragmento_id for r in postgres.search(db_session, provider, modo=mode, **options)}
            # The analyzers are not the same, so a few text matches may differ.
            assert len(a ^ b) <= 0.05 * len(a | b)


def test_while_it_loads_postgres_answers(db_session, embedder, ingest, monkeypatch) -> None:  # noqa: F811
    document = ingest()
    backend = EngineBackend()
    loading, go_on = threading.Event(), threading.Event()
    real = backend._load

    def slow(*args):
        loading.set()
        go_on.wait(10)
        return real(*args)

    monkeypatch.setattr(backend, "_load", slow)
    backend.start(db_session.get_bind(), poll_seconds=0.05)
    try:
        assert loading.wait(10)
        assert not backend.ready
        assert _found(backend, db_session, embedder) == [document.id]
        go_on.set()
        end = time.monotonic() + 10
        while not backend.ready and time.monotonic() < end:
            time.sleep(0.02)
        assert backend.ready
        assert _found(backend, db_session, embedder) == [document.id]
    finally:
        go_on.set()
        backend.stop()


def test_the_background_refresh_survives_errors(db_session, embedder, ingest, monkeypatch) -> None:  # noqa: F811
    backend = EngineBackend()
    real, calls = backend._load, []

    def flaky(*args):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("connection lost")
        return real(*args)

    monkeypatch.setattr(backend, "_load", flaky)
    backend.start(db_session.get_bind(), poll_seconds=0.02)
    try:
        end = time.monotonic() + 10
        while not backend.ready and time.monotonic() < end:
            time.sleep(0.02)
        assert backend.ready
    finally:
        backend.stop()


def test_selection_by_setting(monkeypatch) -> None:
    monkeypatch.delenv("SEARCH_ENGINE", raising=False)
    assert isinstance(backend_from_environment(), PostgresBackend)
    monkeypatch.setenv("SEARCH_ENGINE", "engine")
    monkeypatch.setenv("RRF_WEIGHTS", "1,2.5")
    assert isinstance(backend_from_environment(), EngineBackend)
    monkeypatch.setenv("RRF_WEIGHTS", "1")
    with pytest.raises(ValueError, match="RRF_WEIGHTS"):
        backend_from_environment()
    monkeypatch.setenv("SEARCH_ENGINE", "magic")
    with pytest.raises(ValueError, match="magic"):
        backend_from_environment()


def test_the_service_uses_the_engine_when_it_is_set(db_session, embedder, ingest, monkeypatch) -> None:  # noqa: F811
    from fastapi.testclient import TestClient

    from src.api import main
    from src.config.installation import InstallationConfig

    monkeypatch.setenv("SEARCH_ENGINE", "engine")
    monkeypatch.setattr(main, "get_installation_config", lambda: InstallationConfig(nombre="x", seed=False))
    monkeypatch.setattr(main.deps, "_engine", lambda: db_session.get_bind())
    monkeypatch.setattr(main, "get_embedder", lambda: embedder)
    main.app.dependency_overrides[deps.get_embedder] = lambda: embedder
    main.app.dependency_overrides[deps.get_installation_config] = lambda: InstallationConfig(nombre="x", seed=False)
    deps._search_backend.cache_clear()
    document = ingest()
    try:
        with TestClient(main.app) as client:
            backend = deps.get_search_backend()
            assert isinstance(backend, EngineBackend)
            end = time.monotonic() + 10
            while not backend.ready and time.monotonic() < end:
                time.sleep(0.02)
            body = client.get("/v1/search", params={"q": "texto"}).json()
        assert [r["documento_id"] for r in body["resultados"]] == [document.id]
    finally:
        main.app.dependency_overrides.clear()
        deps._search_backend.cache_clear()
