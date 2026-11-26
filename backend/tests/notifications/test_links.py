"""Plan 10: pausing from an email, without signing in."""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api import deps
from src.api.main import app
from src.notifications.links import LINK_DAYS, pause_token, read_pause_token
from tests.notifications.conftest import SECRET, T0

DAY = datetime.timedelta(days=1)


def test_a_token_is_for_one_subscription() -> None:
    token = pause_token(SECRET, 42, now=T0)
    assert read_pause_token(SECRET, token, now=T0) == 42
    assert pause_token(SECRET, 43, now=T0) != token


@pytest.mark.parametrize("secret", ["other", "", SECRET + "x"])
def test_another_secret_does_not_read_it(secret) -> None:
    assert read_pause_token(secret, pause_token(SECRET, 42, now=T0), now=T0) is None


def test_no_secret_no_token() -> None:
    with pytest.raises(ValueError):
        pause_token("", 42)
    assert read_pause_token("", "anything") is None


@pytest.mark.parametrize("token", ["", "x", "42", "a.b.c", "42.0.", "42..abc", "42.99999999999.AAAA", "é.é.é", "." * 500, "42." * 50])
def test_anything_else_is_not_a_token(token) -> None:
    assert read_pause_token(SECRET, token, now=T0) is None


def test_a_token_cannot_be_changed() -> None:
    token = pause_token(SECRET, 42, now=T0)
    identifier, expires, signature = token.split(".")
    for forged in (f"43.{expires}.{signature}", f"42.{int(expires) + 1}.{signature}", f"42.{expires}.{signature[:-2]}AA",
                   f"042.{expires}.{signature}", f" 42.{expires}.{signature}", token + "A"):  # fmt: skip
        assert read_pause_token(SECRET, forged, now=T0) is None, forged


def test_a_token_expires() -> None:
    token = pause_token(SECRET, 42, now=T0)
    assert read_pause_token(SECRET, token, now=T0 + (LINK_DAYS - 1) * DAY) == 42
    assert read_pause_token(SECRET, token, now=T0 + (LINK_DAYS + 1) * DAY) is None


def test_the_signature_is_for_this_action_only() -> None:
    """The same secret signing the same numbers for something else is not valid here."""
    import base64
    import hashlib
    import hmac

    identifier, expires, _ = pause_token(SECRET, 42, now=T0).split(".")
    for message in (f"{identifier}.{expires}", f"delete.{identifier}.{expires}"):
        digest = hmac.new(SECRET.encode(), message.encode(), hashlib.sha256).digest()
        forged = f"{identifier}.{expires}.{base64.urlsafe_b64encode(digest).decode().rstrip('=')}"
        assert read_pause_token(SECRET, forged, now=T0) is None


@pytest.fixture()
def client(db_session: Session, monkeypatch):
    monkeypatch.setenv("LINK_SECRET", SECRET)

    def session():
        yield db_session

    app.dependency_overrides[deps.get_session] = session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_link_pauses_without_signing_in(client, db_session, make) -> None:
    subscription, other = make.subscription(text="mi tema"), make.subscription()
    token = pause_token(SECRET, subscription.id)
    assert client.get("/v1/pause-links", params={"token": token}).json() == {"texto_busqueda": "mi tema", "estado": "activa"}
    db_session.refresh(subscription)
    assert subscription.estado == "activa", "looking does not pause: mail scanners open the links"
    for _ in range(2):
        response = client.post("/v1/pause-links", json={"token": token})
        assert response.status_code == 200 and response.json()["estado"] == "pausada"
    db_session.refresh(subscription)
    db_session.refresh(other)
    assert (subscription.estado, other.estado) == ("pausada", "activa")


@pytest.mark.parametrize("token", ["", "x", "1.2.3"])
def test_a_wrong_link(client, db_session, make, token) -> None:
    subscription = make.subscription()
    assert client.get("/v1/pause-links", params={"token": token}).status_code == 404
    assert client.post("/v1/pause-links", json={"token": token}).status_code == 404
    db_session.refresh(subscription)
    assert subscription.estado == "activa"


def test_the_link_of_a_deleted_subscription(client) -> None:
    token = pause_token(SECRET, 987)
    assert client.post("/v1/pause-links", json={"token": token}).status_code == 404


def test_without_secret_no_link_works(client, make, monkeypatch) -> None:
    token = pause_token(SECRET, make.subscription().id)
    monkeypatch.setenv("LINK_SECRET", "")
    assert client.post("/v1/pause-links", json={"token": token}).status_code == 404


@pytest.mark.parametrize(("secret", "url", "warned"), [("", "https://x", True), ("s", "", True), ("s", "https://x", False)])
def test_startup_says_that_emails_have_no_pause_link(db_session, monkeypatch, caplog, secret, url, warned) -> None:
    from src.api import main
    from src.config.installation import InstallationConfig

    monkeypatch.setattr(main, "get_installation_config", lambda: InstallationConfig(nombre="x", seed=False))
    monkeypatch.setattr(main.deps, "_engine", lambda: db_session.get_bind())
    monkeypatch.setattr(main, "get_embedder", lambda: None)
    monkeypatch.setattr(main.logger, "disabled", False)
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("LINK_SECRET", secret)
    monkeypatch.setenv("PUBLIC_WEB_URL", url)
    with caplog.at_level("WARNING", logger="contextcrawl"), TestClient(main.app):
        pass
    assert any("LINK_SECRET" in r.getMessage() for r in caplog.records) is warned
