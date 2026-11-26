"""Plan 7: citable results, declared filters on connector documents, issues."""
import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_embedder, get_installation_config, get_session
from src.api.main import app
from src.config.installation import cargar_installation_config, upsert_fuentes
from src.connectors.boletin_cba.connector import ConectorBoletinCba
from src.connectors.comprar_gob_ar.connector import ConectorComprarGobAr
from src.connectors.runner import ejecutar_conector
from src.db.models import Documento, Fuente, Usuario
from src.ingestor.contract import DocumentoNormalizado, ingerir_documento
from src.processor.hashed_embeddings import HashedEmbeddingProvider
from src.synthetic.pdf import write_pdf

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "backend" / "tests" / "fixtures"
EMBEDDER = HashedEmbeddingProvider()


@pytest.fixture()
def make_client(db_session: Session, monkeypatch):
    monkeypatch.setenv("SIMILARITY_THRESHOLD", "0.05")

    def make(installation_file: str = "installation.yaml") -> TestClient:
        installation = cargar_installation_config(ROOT / "config" / installation_file)
        upsert_fuentes(db_session, installation)

        def session():
            yield db_session

        app.dependency_overrides[get_session] = session
        app.dependency_overrides[get_embedder] = lambda: EMBEDDER
        app.dependency_overrides[get_installation_config] = lambda: installation
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def _run(session: Session, source: str, connector, config: dict) -> None:
    fuente = session.scalar(select(Fuente).where(Fuente.clave == source))
    run = ejecutar_conector(session, EMBEDDER, fuente, connector, config, version_conector="test")
    assert run.errores == 0, run.detalle_errores


def _gazette(session: Session, url: str | None = None, section: int = 4, source: str = "cordoba-provincial") -> None:
    url = url or (FIXTURES / "boletin_cba" / "4_Secc_sample.pdf").as_uri()
    config = {"url_template": url, "secciones": [section], "fecha": "2026-09-24"}
    _run(session, source, ConectorBoletinCba(), config)


def _search(client: TestClient, q: str, **params) -> list[dict]:
    response = client.get("/v1/search", params={"q": q, "limit": 50, **params})
    assert response.status_code == 200, response.text
    return response.json()["resultados"]


def test_a_result_cites_its_notice_and_page(db_session: Session, make_client) -> None:
    client = make_client()
    _gazette(db_session)
    best = _search(client, "adquisición de materiales para parque solar fotovoltaico")[0]
    assert best["notice_number"] == "688769"
    assert best["issue"] == "4_Secc_240926"
    assert best["page"] == 4
    assert (best["first_page"], best["last_page"]) == (4, 5)
    assert best["url_fuente"].endswith("#page=4")
    assert best["titulo"].startswith("Aviso Nº 688769")
    assert best["segmented"] is True


@pytest.mark.parametrize("mode", ["semantic", "hybrid", "all"])
def test_every_result_of_a_segmented_source_has_a_number_and_a_page(db_session: Session, make_client, mode) -> None:
    client = make_client()
    _gazette(db_session)
    for q in ("licitaciones subastas convocatorias sumario", "ministerio", "notificaciones", "688923"):
        results = _search(client, q, mode=mode)
        assert results or mode != "all"
        for r in results:
            assert r["notice_number"] and r["page"] and r["first_page"] <= r["page"] <= r["last_page"]


def test_an_unsegmented_document_says_so_and_has_a_page(db_session: Session, make_client, tmp_path) -> None:
    client = make_client()
    path = tmp_path / "issue.pdf"
    path.write_bytes(write_pdf(["Decreto provincial sobre presupuesto.", "Artículo 1. Publíquese."]))
    _gazette(db_session, path.as_uri(), section=1)
    (result,) = _search(client, "decreto presupuesto")
    assert result["segmented"] is False and result["notice_number"] is None
    assert result["page"] == 1


def test_other_documents_have_no_notice_data(db_session: Session, make_client) -> None:
    client = make_client()
    ingerir_documento(
        db_session,
        EMBEDDER,
        DocumentoNormalizado("carlos-paz-municipal", "B1", datetime.date(2026, 1, 1), "ordenanza", "https://example.org"),
    )
    (result,) = _search(client, "ordenanza")
    for key in ("notice_number", "page", "first_page", "last_page", "issue", "segmented"):
        assert result[key] is None


# A test searches with each declared filter and finds connector documents.


def test_provincia_filter_finds_gazette_documents(db_session: Session, make_client) -> None:
    client = make_client()
    _gazette(db_session)
    results = _search(client, "licitación pública", **{"filtro.provincia": "Córdoba"})
    assert results and all(r["notice_number"] for r in results)
    assert _search(client, "licitación pública", **{"filtro.provincia": "San Luis"}) == []


def test_municipio_filter_finds_gazette_documents(db_session: Session, make_client, tmp_path) -> None:
    client = make_client()
    path = tmp_path / "issue.pdf"
    closing = "1 día - Nº {} - s/c - 24/9/2026 - BOE"
    path.write_bytes(
        write_pdf([
            f"MUNICIPALIDAD DE CARLOS PAZ\nOrdenanza de tránsito.\n{closing.format(1)}\n"
            f"MUNICIPALIDAD DE NOETINGER\nOrdenanza de tránsito.\n{closing.format(2)}"
        ])
    )
    _gazette(db_session, path.as_uri(), section=5)
    results = _search(client, "ordenanza de tránsito", **{"filtro.municipio": "Noetinger"})
    assert [r["notice_number"] for r in results] == ["2"]


def test_organismo_and_monto_filters_find_tender_documents(db_session: Session, make_client) -> None:
    client = make_client("installation-licitaciones.yaml")
    csv = (FIXTURES / "comprar_gob_ar" / "convocatorias_sample.csv").as_uri()
    _run(db_session, "comprar-ar-nacional", ConectorComprarGobAr(), {"csv_url": csv, "limite_filas": 20})
    sample = db_session.scalars(select(Documento).where(Documento.metadata_.has_key("monto"))).first()
    body, amount = sample.metadata_["organismo"], sample.metadata_["monto"]
    found = _search(client, sample.texto, mode="all", **{"filtro.organismo": body})
    assert sample.identificador_externo in {r["identificador_externo"] for r in found}
    found = _search(client, sample.texto, mode="all", **{"filtro.monto": f"{amount - 1},{amount + 1}"})
    assert sample.identificador_externo in {r["identificador_externo"] for r in found}


def test_the_notices_of_an_issue_are_listed_together(db_session: Session, make_client) -> None:
    client = make_client()
    _gazette(db_session)
    response = client.get("/v1/issues/cordoba-provincial/4_Secc_240926")
    assert response.status_code == 200
    body = response.json()
    assert body["fecha"] == "2026-09-24"
    assert len(body["documents"]) == 36
    numbers = [d["notice_number"] for d in body["documents"] if d["notice_number"]]
    assert numbers[:3] == ["688404", "688627", "688872"] and numbers[-1] == "687583"
    assert body["documents"][0]["first_page"] == 1
    assert body["url_fuente"].endswith("4_Secc_sample.pdf")


@pytest.mark.parametrize("path", ["cordoba-provincial/nope", "nope/4_Secc_240926"])
def test_an_unknown_issue_is_not_found(db_session: Session, make_client, path) -> None:
    assert make_client().get(f"/v1/issues/{path}").status_code == 404


def test_an_alert_says_where_to_find_the_notice(db_session: Session, make_client, monkeypatch) -> None:
    from src.db.models import Suscripcion
    from src.notifications import dispatcher

    sent = []
    monkeypatch.setattr(dispatcher, "enviar_correo", lambda **mail: sent.append(mail))
    client = make_client()
    user = Usuario(email="a@example.org", password_hash="x")
    db_session.add(user)
    db_session.flush()
    text = "parque solar fotovoltaico concurso de precios cooperativa Villa Ascasubi"
    db_session.add(
        Suscripcion(usuario_id=user.id, texto_busqueda=text, embedding=EMBEDDER.embed_query(text), canales=["correo"])
    )
    db_session.commit()
    monkeypatch.setenv("SIMILARITY_THRESHOLD", "0.2")
    _gazette(db_session)
    assert len(sent) == 1
    assert "Aviso Nº 688769" in sent[0]["cuerpo"]
    assert "Páginas 4 a 5" in sent[0]["cuerpo"]
    assert "#page=4" in sent[0]["cuerpo"]

    from src.api.deps import get_usuario_actual

    app.dependency_overrides[get_usuario_actual] = lambda: user
    (delivery,) = client.get("/v1/notificaciones").json()
    assert delivery["notice_number"] == "688769"
    assert (delivery["first_page"], delivery["last_page"]) == (4, 5)
    assert delivery["url_fuente"].endswith("#page=4")
