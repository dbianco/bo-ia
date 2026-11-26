"""Plan 10: the inbox, with its explanations and read state, and the settings of a subscription."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api import deps
from src.api.main import app
from src.config.installation import InstallationConfig
from src.db.models import Usuario
from src.processor.embeddings import FakeEmbeddingProvider
from tests.notifications.conftest import make  # noqa: F401


@pytest.fixture()
def client(db_session: Session):
    def session():
        yield db_session

    app.dependency_overrides[deps.get_session] = session
    app.dependency_overrides[deps.get_embedder] = lambda: FakeEmbeddingProvider()
    app.dependency_overrides[deps.get_installation_config] = lambda: InstallationConfig(nombre="x")
    yield TestClient(app)
    app.dependency_overrides.clear()


def _sign_in(client: TestClient, db_session: Session, address: str = "a@example.org") -> Usuario:
    data = {"email": address, "password": "una-contraseña-larga"}
    client.post("/v1/auth/registro", json=data)
    assert client.post("/v1/auth/login", json=data).status_code == 200
    return db_session.query(Usuario).filter_by(email=address).one()


def _inbox(client: TestClient, **params) -> list[dict]:
    response = client.get("/v1/notificaciones", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_an_entry_explains_itself(client, db_session, make) -> None:  # noqa: F811
    user = _sign_in(client, db_session)
    subscription = make.subscription(user, filters={"provincia": {"tipo": "seleccion", "valor": "Córdoba"}})
    make.match(subscription, make.document("Obras de pavimentación en la calle Colón.", notice_number="7", first_page=3, last_page=3))
    entry = next(e for e in _inbox(client) if e["canal"] == "bandeja")
    assert entry["titulo"].startswith("Documento") and entry["url_fuente"].startswith("https://example.org/")
    assert entry["texto_busqueda"] == "pavimentación de calles" and entry["score"] == 0.87
    assert entry["fecha"] == "2026-06-01" and entry["notice_number"] == "7" and entry["page"] == 3
    assert entry["filtros"] == {"provincia": "Córdoba"}
    assert entry["shared_words"] == ["pavimentación", "calle"]
    assert "".join(p["text"] for p in entry["excerpt"]) == "Obras de pavimentación en la calle Colón."
    assert [p["text"] for p in entry["excerpt"] if p["match"]] == ["pavimentación", "calle"]
    assert entry["read_at"] is None


def test_a_match_by_meaning_has_no_shared_words(client, db_session, make) -> None:  # noqa: F811
    user = _sign_in(client, db_session)
    make.match(make.subscription(user, "combustible"), make.document("Gasoil y nafta."))
    entry = _inbox(client)[0]
    assert entry["shared_words"] == [] and not any(p["match"] for p in entry["excerpt"])


def test_entries_can_be_marked_as_read(client, db_session, make) -> None:  # noqa: F811
    user = _sign_in(client, db_session)
    subscription = make.subscription(user, channels=["bandeja"])
    for _ in range(3):
        make.match(subscription)
    ids = [e["id"] for e in _inbox(client)]
    first = client.post(f"/v1/notificaciones/{ids[0]}/read")
    assert first.status_code == 200 and first.json()["read_at"]
    again = client.post(f"/v1/notificaciones/{ids[0]}/read")
    assert again.json()["read_at"] == first.json()["read_at"], "the first time counts"
    assert [e["id"] for e in _inbox(client, unread=True)] == ids[1:]
    assert client.get("/v1/notificaciones/unread-count").json() == {"unread": 2}
    assert client.post("/v1/notificaciones/read").json() == {"read": 2}
    assert _inbox(client, unread=True) == [] and len(_inbox(client)) == 3


def test_the_entries_of_another_user(client, db_session, make) -> None:  # noqa: F811
    owner = make.user("other@example.org")
    match = make.match(make.subscription(owner, channels=["bandeja"]))
    _sign_in(client, db_session)
    assert _inbox(client) == []
    assert client.post(f"/v1/notificaciones/{match.entregas[0].id}/read").status_code == 404
    assert client.post("/v1/notificaciones/read").json() == {"read": 0}
    db_session.refresh(match.entregas[0])
    assert match.entregas[0].read_at is None


@pytest.mark.parametrize(("method", "path"), [("GET", "/v1/notificaciones"), ("GET", "/v1/notificaciones/unread-count"),
                                              ("POST", "/v1/notificaciones/1/read"), ("POST", "/v1/notificaciones/read"),
                                              ("PATCH", "/v1/suscripciones/1")])  # fmt: skip
def test_a_session_is_needed(client, method, path) -> None:
    assert client.request(method, path, json={} if method == "PATCH" else None).status_code == 401


def test_channel_and_paging(client, db_session, make) -> None:  # noqa: F811
    user = _sign_in(client, db_session)
    subscription = make.subscription(user)
    for _ in range(5):
        make.match(subscription)
    assert {e["canal"] for e in _inbox(client)} == {"bandeja", "correo"}
    inbox = _inbox(client, canal="bandeja")
    assert len(inbox) == 5 and inbox[0]["id"] > inbox[-1]["id"], "the newest first"
    page = _inbox(client, canal="bandeja", limit=2)
    following = _inbox(client, canal="bandeja", limit=2, before=page[-1]["id"])
    assert [e["id"] for e in page + following] == [e["id"] for e in inbox[:4]]
    assert client.get("/v1/notificaciones", params={"limit": 0}).status_code == 422
    assert client.get("/v1/notificaciones", params={"limit": 1000}).status_code == 422


def _statements(session: Session, work) -> int:
    from sqlalchemy import event

    statements = []

    def listener(*args) -> None:
        statements.append(args[2])

    event.listen(session.get_bind(), "before_cursor_execute", listener)
    work()
    event.remove(session.get_bind(), "before_cursor_execute", listener)
    return len(statements)


def test_listing_takes_the_same_queries_however_many_there_are(client, db_session, make) -> None:  # noqa: F811
    user = _sign_in(client, db_session)
    counts = []
    for size in (2, 10):
        subscription = make.subscription(user, channels=["bandeja"])
        for _ in range(size):
            make.match(subscription)
        db_session.expire_all()
        counts.append(_statements(db_session, lambda: _inbox(client)))
    assert counts[0] == counts[1]


# --- settings of a subscription ---


@pytest.mark.parametrize("frequency", ["immediate", "daily", "weekly"])
def test_a_subscription_has_a_frequency(client, db_session, frequency) -> None:
    _sign_in(client, db_session)
    body = {"texto_busqueda": "x", "canales": ["correo"], "frecuencia_notificacion": frequency}
    created = client.post("/v1/suscripciones", json=body)
    assert created.status_code == 201 and created.json()["frecuencia_notificacion"] == frequency
    assert client.get("/v1/suscripciones").json()[0]["frecuencia_notificacion"] == frequency


def test_the_frequency_is_immediate_if_it_is_not_said(client, db_session) -> None:
    _sign_in(client, db_session)
    assert client.post("/v1/suscripciones", json={"texto_busqueda": "x"}).json()["frecuencia_notificacion"] == "immediate"


@pytest.mark.parametrize("value", ["hourly", "", None, 5])
def test_another_frequency_is_an_error(client, db_session, value) -> None:
    _sign_in(client, db_session)
    body = {"texto_busqueda": "x", "frecuencia_notificacion": value}
    assert client.post("/v1/suscripciones", json=body).status_code == 422


def test_channels_and_frequency_can_be_changed(client, db_session) -> None:
    _sign_in(client, db_session)
    identifier = client.post("/v1/suscripciones", json={"texto_busqueda": "x"}).json()["id"]
    changed = client.patch(f"/v1/suscripciones/{identifier}", json={"canales": ["correo"], "frecuencia_notificacion": "daily"})
    assert changed.status_code == 200
    assert (changed.json()["canales"], changed.json()["frecuencia_notificacion"]) == (["correo"], "daily")
    only = client.patch(f"/v1/suscripciones/{identifier}", json={"frecuencia_notificacion": "weekly"}).json()
    assert (only["canales"], only["frecuencia_notificacion"], only["texto_busqueda"]) == (["correo"], "weekly", "x")
    for body in ({"canales": ["fax"]}, {"frecuencia_notificacion": "x"}, {"canales": []}):
        assert client.patch(f"/v1/suscripciones/{identifier}", json=body).status_code == 422
    assert client.patch("/v1/suscripciones/9999", json={}).status_code == 404


def test_the_subscription_of_another_user_cannot_be_changed(client, db_session, make) -> None:  # noqa: F811
    other = make.subscription(make.user("other@example.org"))
    _sign_in(client, db_session)
    assert client.patch(f"/v1/suscripciones/{other.id}", json={"canales": ["correo"]}).status_code == 404
