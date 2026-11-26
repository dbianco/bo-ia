"""Plan 15, defect A: only authorized callers can add documents or run a source."""
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api import deps, fuentes, main
from src.api.main import app
from src.config.installation import ConectorConfig, FuenteConfig, InstallationConfig
from src.db.models import Documento, EjecucionFuente, Fuente, MatchingQueue
from src.ingestor.contract import DocumentoNormalizado
from src.processor.embeddings import FakeEmbeddingProvider

TOKEN = "s3cr3t-ñ-token-for-tests"
DOCUMENT = {
    "fuente_clave": "f", "identificador_externo": "d", "fecha": "2026-01-01", "texto": "texto",
    "url_fuente": "https://example.org",
}  # fmt: skip
ENDPOINTS = [("/v1/documentos", DOCUMENT), ("/v1/fuentes/f/ejecutar", None)]


class _Connector:
    calls = 0

    def descubrir(self, *, fuente_clave, config):
        _Connector.calls += 1
        import datetime

        yield DocumentoNormalizado(fuente_clave, "run", datetime.date(2026, 1, 1), "otro", "https://example.org")


@pytest.fixture()
def client(db_session: Session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(fuentes.CONECTORES, "fake", _Connector)
    monkeypatch.setitem(fuentes.VERSIONES, "fake", "v")
    monkeypatch.setenv("OPERATOR_TOKEN", TOKEN)
    _Connector.calls = 0
    db_session.add(Fuente(clave="f", nombre="f", config={}))
    db_session.commit()
    installation = InstallationConfig(
        nombre="x", fuentes=[FuenteConfig(clave="f", nombre="f", conector=ConectorConfig(tipo="fake", frecuencia_minutos=1))]
    )

    def session():
        yield db_session

    app.dependency_overrides[deps.get_session] = session
    app.dependency_overrides[deps.get_embedder] = lambda: FakeEmbeddingProvider()
    app.dependency_overrides[deps.get_installation_config] = lambda: installation
    yield TestClient(app)
    app.dependency_overrides.clear()


def _bearer(token: str) -> dict:
    return {"Authorization": b"Bearer " + token.encode()}


def _nothing_happened(session: Session) -> bool:
    session.expire_all()
    counts = [session.scalar(select(func.count()).select_from(t)) for t in (Documento, EjecucionFuente, MatchingQueue)]
    return counts == [0, 0, 0] and _Connector.calls == 0


@pytest.mark.parametrize(("path", "body"), ENDPOINTS)
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer wrong"},
        _bearer(TOKEN[:-1]),
        _bearer(TOKEN + "x"),
        _bearer(TOKEN.upper()),
        {"Authorization": b"Basic " + TOKEN.encode()},
        {"Authorization": TOKEN.encode()},
        {"X-Operator-Token": TOKEN.encode()},
    ],
    ids=["none", "empty", "no token", "blank", "wrong", "shorter", "longer", "case", "basic", "no scheme", "other header"],
)
def test_a_missing_or_wrong_token_is_rejected_and_changes_nothing(
    client: TestClient, db_session: Session, path, body, headers
) -> None:
    response = client.post(path, json=body, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert TOKEN not in response.text
    assert _nothing_happened(db_session)


@pytest.mark.parametrize(("path", "body"), ENDPOINTS)
@pytest.mark.parametrize("configured", [None, "", "   "])
@pytest.mark.parametrize("sent", [None, "", "   ", "None", TOKEN])
def test_with_no_token_configured_every_request_is_rejected(
    client: TestClient, db_session: Session, monkeypatch, path, body, configured, sent
) -> None:
    if configured is None:
        monkeypatch.delenv("OPERATOR_TOKEN")
    else:
        monkeypatch.setenv("OPERATOR_TOKEN", configured)
    response = client.post(path, json=body, headers={} if sent is None else _bearer(sent))
    assert response.status_code == 401
    assert _nothing_happened(db_session)


@pytest.mark.parametrize("scheme", ["Bearer", "bearer"])
def test_the_right_token_works_as_before(client: TestClient, scheme) -> None:
    headers = {"Authorization": f"{scheme} ".encode() + TOKEN.encode()}
    response = client.post("/v1/documentos", json=DOCUMENT, headers=headers)
    assert response.status_code == 201 and response.json()["estado"] == "completo"
    response = client.post("/v1/fuentes/f/ejecutar", headers=headers)
    assert response.status_code == 200 and response.json()["nuevos"] == 1


def test_spaces_around_the_configured_token_do_not_matter(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("OPERATOR_TOKEN", f" {TOKEN}\n")
    assert client.post("/v1/documentos", json=DOCUMENT, headers=_bearer(TOKEN)).status_code == 201


def test_the_token_is_checked_before_anything_else(client: TestClient) -> None:
    """An outsider learns nothing about sources, nor about the format."""
    assert client.post("/v1/documentos", json={"nonsense": 1}).status_code == 401
    assert client.post("/v1/fuentes/does-not-exist/ejecutar").status_code == 401


def test_a_user_session_is_not_enough(client: TestClient, db_session: Session) -> None:
    data = {"email": "a@example.org", "password": "una-contraseña-larga"}
    client.post("/v1/auth/registro", json=data)
    assert client.post("/v1/auth/login", json=data).status_code == 200
    for path, body in ENDPOINTS:
        assert client.post(path, json=body).status_code == 401
    assert _nothing_happened(db_session)


def test_the_comparison_takes_constant_time(client: TestClient, monkeypatch) -> None:
    import hmac

    compared = []
    real = hmac.compare_digest
    monkeypatch.setattr(hmac, "compare_digest", lambda a, b: compared.append((a, b)) or real(a, b))
    client.post("/v1/documentos", json=DOCUMENT, headers=_bearer("wrong"))
    assert compared == [(b"wrong", TOKEN.encode())]


def test_the_token_is_never_logged(client: TestClient, caplog) -> None:
    with caplog.at_level(logging.DEBUG):
        client.post("/v1/documentos", json=DOCUMENT, headers=_bearer(TOKEN))
        client.post("/v1/documentos", json=DOCUMENT, headers=_bearer("another-s3cr3t"))
        client.post("/v1/fuentes/f/ejecutar", headers=_bearer(TOKEN))
    assert TOKEN not in caplog.text and "another-s3cr3t" not in caplog.text


@pytest.mark.parametrize(("token", "warned"), [(None, True), ("", True), (TOKEN, False)])
def test_startup_says_that_the_endpoints_are_closed(db_session: Session, monkeypatch, caplog, token, warned) -> None:
    monkeypatch.setattr(main, "get_installation_config", lambda: InstallationConfig(nombre="x", seed=False))
    monkeypatch.setattr(main.deps, "_engine", lambda: db_session.get_bind())
    monkeypatch.setattr(main, "get_embedder", lambda: None)
    monkeypatch.setattr(main.logger, "disabled", False)  # the migrations of the fixture disable it
    if token is None:
        monkeypatch.delenv("OPERATOR_TOKEN", raising=False)
    else:
        monkeypatch.setenv("OPERATOR_TOKEN", token)
    with caplog.at_level("WARNING", logger="contextcrawl"), TestClient(main.app):
        pass
    assert any("OPERATOR_TOKEN" in r.getMessage() for r in caplog.records) is warned
    assert TOKEN not in caplog.text


def test_every_route_that_writes_is_known() -> None:
    """A new endpoint that writes has to be put here on purpose, with who may call it."""
    operator = {("POST", "/v1/documentos"), ("POST", "/v1/fuentes/{clave}/ejecutar")}
    own_session = {
        ("POST", "/v1/suscripciones"),
        ("POST", "/v1/suscripciones/{suscripcion_id}/pausar"),
        ("POST", "/v1/suscripciones/{suscripcion_id}/reanudar"),
        ("DELETE", "/v1/suscripciones/{suscripcion_id}"),
    }
    # On purpose: registering, signing in and out, and rating a search result.
    anybody = {
        ("POST", "/v1/auth/registro"),
        ("POST", "/v1/auth/login"),
        ("POST", "/v1/auth/logout"),
        ("POST", "/v1/valoraciones"),
    }
    found = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method.upper() not in {"GET", "HEAD", "OPTIONS"}
    }
    assert found == operator | own_session | anybody


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/v1/suscripciones"), ("POST", "/v1/suscripciones/1/pausar"), ("POST", "/v1/suscripciones/1/reanudar"),
     ("DELETE", "/v1/suscripciones/1")],
)  # fmt: skip
def test_the_endpoints_of_a_user_need_a_session(client: TestClient, method, path) -> None:
    body = {"texto_busqueda": "x"} if path.endswith("suscripciones") else None
    assert client.request(method, path, json=body).status_code == 401


def test_reading_stays_public(client: TestClient) -> None:
    assert client.get("/v1/config").status_code == 200
    assert client.get("/health").status_code == 200
