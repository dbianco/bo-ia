"""Plan 10: the web screens, against the real API in this process. The web is a
separate application without tests of its own."""
import importlib.util
import re
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api import deps
from src.api.main import app as backend
from src.config.installation import FiltroSeleccion, InstallationConfig
from src.db.models import EntregaNotificacion, Suscripcion, Usuario
from src.notifications.links import pause_token
from src.processor.embeddings import FakeEmbeddingProvider
from tests.notifications.conftest import make  # noqa: F401

WEB = Path(__file__).resolve().parents[3] / "web"
EVIL = '<script>alert("x")</script><img src=x onerror=alert(1)>\'"'
PASSWORD = "una-contraseña-larga"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("contextcrawl_web", WEB / "app.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@pytest.fixture()
def api_calls() -> list:
    return []


@pytest.fixture()
def web(module, db_session: Session, monkeypatch, api_calls):
    monkeypatch.setenv("SIMILARITY_THRESHOLD", "0")
    monkeypatch.setenv("LINK_SECRET", "s")

    def session():
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    backend.dependency_overrides[deps.get_session] = session
    backend.dependency_overrides[deps.get_embedder] = lambda: FakeEmbeddingProvider()
    backend.dependency_overrides[deps.get_installation_config] = lambda: InstallationConfig(
        nombre="Boletines de prueba", filtros=[FiltroSeleccion(clave="provincia", etiqueta="Provincia")]
    )

    @contextmanager
    def client(timeout: float = 10.0):
        api = TestClient(backend)
        api.event_hooks = {"request": [api_calls.append]}
        yield api

    monkeypatch.setattr(module, "backend_client", client)
    yield TestClient(module.app, base_url="http://alerts.test", follow_redirects=True)
    backend.dependency_overrides.clear()


def _sign_up(web: TestClient, address: str = "cliente@example.org") -> None:
    response = web.post("/registro", data={"email": address, "password": PASSWORD})
    assert response.status_code == 200 and response.url.path == "/bandeja"


class _Tags(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict]] = []
        self.feed(html)

    def handle_starttag(self, tag, attrs) -> None:
        self.tags.append((tag, dict(attrs)))


def _assert_no_injection(html: str) -> None:
    for tag, attributes in _Tags(html).tags:
        assert not any(name.startswith("on") for name in attributes), (tag, attributes)
        assert tag != "img"
        if tag == "script":
            assert set(attributes) <= {"src"} and not (attributes.get("src") or "/static/").startswith("http")
        if "href" in attributes:
            assert attributes["href"].startswith(("/", "http://", "https://", "#")), attributes["href"]
    assert "<script>alert" not in html and 'alert("x")' not in html


# --- accounts ---


def test_signing_up_in_and_out(web, db_session) -> None:
    _sign_up(web)
    assert db_session.query(Usuario).one().email == "cliente@example.org"
    out = web.post("/salir")
    assert out.url.path == "/" and web.get("/bandeja").url.path == "/ingresar"
    assert web.post("/ingresar", data={"email": "cliente@example.org", "password": PASSWORD}).url.path == "/bandeja"


def test_the_session_cookie_is_not_for_scripts(web) -> None:
    web.follow_redirects = False
    web.post("/registro", data={"email": "a@example.org", "password": PASSWORD})
    cookie = web.post("/ingresar", data={"email": "a@example.org", "password": PASSWORD}).headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie and "secure" not in cookie


def test_with_a_secure_address_the_cookie_is_secure(web, monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_WEB_URL", "https://alerts.example.org")
    web.follow_redirects = False
    response = web.post("/registro", data={"email": "a@example.org", "password": PASSWORD})
    assert "secure" in response.headers["set-cookie"].lower()


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"email": "cliente@example.org", "password": "incorrecta"}, "incorrectos"),
        ({"email": "nadie@example.org", "password": PASSWORD}, "incorrectos"),
    ],
)
def test_wrong_credentials(web, data, message) -> None:
    _sign_up(web)
    web.post("/salir")
    response = web.post("/ingresar", data=data)
    assert response.status_code == 401 and message in response.text and data["email"] in response.text
    assert PASSWORD not in response.text and "incorrecta\"" not in response.text


@pytest.mark.parametrize(
    ("data", "status"),
    [({"email": "cliente@example.org", "password": PASSWORD}, 409), ({"email": "x", "password": PASSWORD}, 422),
     ({"email": "b@example.org", "password": "corta"}, 422)],
)  # fmt: skip
def test_a_registration_that_is_not_valid(web, data, status) -> None:
    _sign_up(web)
    web.post("/salir")
    response = web.post("/registro", data=data)
    assert response.status_code == status and 'role="alert"' in response.text


@pytest.mark.parametrize("path", ["/bandeja", "/suscripciones"])
def test_the_private_pages_ask_to_sign_in_and_come_back(web, path) -> None:
    response = web.get(path)
    assert response.url.path == "/ingresar" and response.url.params["next"] == path
    _sign_up(web)
    web.post("/salir")
    back = web.post("/ingresar", data={"email": "cliente@example.org", "password": PASSWORD, "next": path})
    assert back.url.path == path


@pytest.mark.parametrize("target", ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "\\/x", ""])
def test_signing_in_does_not_lead_to_another_site(web, target) -> None:
    _sign_up(web)
    web.post("/salir")
    response = web.post("/ingresar", data={"email": "cliente@example.org", "password": PASSWORD, "next": target})
    assert str(response.url) == "http://alerts.test/bandeja"


def test_a_session_that_ended(web, db_session) -> None:
    from src.db.models import Sesion

    _sign_up(web)
    db_session.query(Sesion).delete()
    db_session.commit()
    assert web.get("/bandeja").url.path == "/ingresar"
    assert web.get("/").status_code == 200


# --- requests from another site ---


@pytest.mark.parametrize(
    "headers",
    [{"Origin": "https://evil.example"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"},
     {"Sec-Fetch-Site": "same-site"}, {"Origin": "http://alerts.test.evil.example"}],
)  # fmt: skip
@pytest.mark.parametrize("path", ["/salir", "/suscripciones", "/bandeja/leer-todo", "/pausar", "/ingresar"])
def test_a_form_of_another_site_is_refused(web, db_session, path, headers) -> None:
    _sign_up(web)
    response = web.post(path, headers=headers, data={"texto_busqueda": "x", "email": "a", "password": "b", "token": "t"})
    assert response.status_code == 403
    assert db_session.query(Suscripcion).count() == 0


@pytest.mark.parametrize("headers", [{}, {"Origin": "http://alerts.test"}, {"Sec-Fetch-Site": "same-origin", "Origin": "http://alerts.test"}])
def test_a_form_of_this_site_is_accepted(web, db_session, headers) -> None:
    _sign_up(web)
    assert web.post("/suscripciones", headers=headers, data={"texto_busqueda": "x"}).status_code == 200
    assert db_session.query(Suscripcion).count() == 1


def test_behind_a_proxy_the_public_address_counts(web, monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_WEB_URL", "https://alerts.example.org")
    web.follow_redirects = False
    assert web.post("/salir", headers={"Origin": "https://alerts.example.org"}).status_code == 303


# --- subscriptions ---


def test_managing_a_subscription(web, db_session) -> None:
    _sign_up(web)
    page = web.post(
        "/suscripciones",
        data={"texto_busqueda": "obra vial", "filtro.provincia": "Córdoba", "canal": ["bandeja", "correo"],
              "frecuencia_notificacion": "daily"},
    )  # fmt: skip
    assert page.url.path == "/suscripciones" and "obra vial" in page.text and "Córdoba" in page.text
    row = db_session.query(Suscripcion).one()
    assert (row.canales, row.frecuencia_notificacion, row.estado) == (["bandeja", "correo"], "daily", "activa")
    assert row.filtros == {"provincia": {"tipo": "seleccion", "valor": "Córdoba"}}

    def state() -> str:
        db_session.expire_all()
        return db_session.query(Suscripcion).one().estado

    assert "Reanudar" in web.post(f"/suscripciones/{row.id}/pausar").text and state() == "pausada"
    assert "Pausar" in web.post(f"/suscripciones/{row.id}/reanudar").text and state() == "activa"
    web.post(f"/suscripciones/{row.id}/ajustes", data={"canal": ["correo"], "frecuencia_notificacion": "weekly"})
    db_session.expire_all()
    row = db_session.query(Suscripcion).one()
    assert (row.canales, row.frecuencia_notificacion) == (["correo"], "weekly")
    web.post(f"/suscripciones/{row.id}/borrar")
    assert db_session.query(Suscripcion).count() == 0


def test_the_current_settings_are_shown(web) -> None:
    _sign_up(web)
    page = web.post("/suscripciones", data={"texto_busqueda": "x", "canal": ["correo"], "frecuencia_notificacion": "weekly"})
    tags = _Tags(page.text).tags
    settings_form = [a for t, a in tags if t == "option" and "selected" in a]
    assert settings_form and settings_form[-1]["value"] == "weekly"
    assert [a["value"] for t, a in tags if t == "input" and a.get("name") == "canal" and "checked" in a][-1] == "correo"


def test_a_subscription_without_channels_is_an_error(web, db_session) -> None:
    _sign_up(web)
    web.post("/suscripciones", data={"texto_busqueda": "x"})
    row = db_session.query(Suscripcion).one()
    response = web.post(f"/suscripciones/{row.id}/ajustes", data={"frecuencia_notificacion": "daily"})
    assert response.status_code == 422 and 'role="alert"' in response.text


def test_the_subscription_of_another_user(web, db_session, make) -> None:  # noqa: F811
    other = make.subscription(make.user("otro@example.org"))
    _sign_up(web)
    assert web.post(f"/suscripciones/{other.id}/pausar").status_code == 404
    db_session.refresh(other)
    assert other.estado == "activa"


def test_an_empty_subscription_is_refused(web, db_session) -> None:
    _sign_up(web)
    assert web.post("/suscripciones", data={"texto_busqueda": "  "}).status_code == 422
    assert db_session.query(Suscripcion).count() == 0


# --- inbox ---


def test_the_inbox_shows_what_matched_and_why(web, db_session, make) -> None:  # noqa: F811
    _sign_up(web)
    user = db_session.query(Usuario).one()
    subscription = make.subscription(user, "pavimentación de calles", filters={"provincia": {"tipo": "seleccion", "valor": "Córdoba"}})
    make.match(subscription, make.document("Obras de pavimentación en la calle Colón.", titulo="Aviso Nº 7", notice_number="7", first_page=3, last_page=4))
    page = web.get("/bandeja").text
    for expected in ("Aviso Nº 7", "<mark>pavimentación</mark>", "<mark>calle</mark>", "páginas 3 a 4", "0,87", "Córdoba",
                     "pavimentación de calles"):  # fmt: skip
        assert expected in page, expected
    assert page.count("Aviso Nº 7") >= 1 and page.count('class="aviso') == 1, "the email is not another entry"


def test_a_match_by_meaning(web, db_session, make) -> None:  # noqa: F811
    _sign_up(web)
    make.match(make.subscription(db_session.query(Usuario).one(), "combustible"), make.document("Gasoil."))
    page = web.get("/bandeja").text
    assert "por su significado" in page and "<mark>" not in page


def test_marking_as_read(web, db_session, make) -> None:  # noqa: F811
    _sign_up(web)
    subscription = make.subscription(db_session.query(Usuario).one(), channels=["bandeja"])
    for _ in range(3):
        make.match(subscription)
    first = db_session.query(EntregaNotificacion).first()
    assert "Avisos (3)" in web.get("/").text
    web.post(f"/bandeja/{first.id}/leer")
    assert "Avisos (2)" in web.get("/bandeja").text
    assert web.get("/bandeja", params={"sin_leer": "1"}).text.count('class="aviso') == 2
    page = web.post("/bandeja/leer-todo").text
    assert "Avisos (" not in page and web.get("/bandeja").text.count('class="aviso') == 3


def test_paging(web, db_session, make, module, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(module, "PAGE", 2)
    _sign_up(web)
    subscription = make.subscription(db_session.query(Usuario).one(), channels=["bandeja"])
    for i in range(5):
        make.match(subscription, make.document(titulo=f"T{i}T"))
    seen, path = [], "/bandeja"
    for _ in range(5):
        page = web.get(path).text
        seen += re.findall(r"T\dT", page)
        following = re.search(r'href="(/bandeja\?[^"]*before=[^"]*)"', page)
        if not following:
            break
        path = following.group(1).replace("&amp;", "&")
    assert list(dict.fromkeys(seen)) == ["T4T", "T3T", "T2T", "T1T", "T0T"]


def test_an_empty_inbox(web) -> None:
    _sign_up(web)
    assert "No tenés avisos" in web.get("/bandeja").text


# --- pausing from an email ---


def test_the_pause_link(web, db_session, make) -> None:  # noqa: F811
    subscription = make.subscription(text="mi tema")
    token = pause_token("s", subscription.id)
    page = web.get("/pausar", params={"token": token})
    assert page.status_code == 200 and "mi tema" in page.text
    db_session.refresh(subscription)
    assert subscription.estado == "activa"
    done = web.post("/pausar", data={"token": token})
    assert done.status_code == 200 and "pausada" in done.text
    db_session.refresh(subscription)
    assert subscription.estado == "pausada"
    assert "ya está pausada" in web.get("/pausar", params={"token": token}).text


@pytest.mark.parametrize("token", ["", "x", EVIL])
def test_a_wrong_pause_link(web, token) -> None:
    for response in (web.get("/pausar", params={"token": token}), web.post("/pausar", data={"token": token})):
        assert response.status_code == 404 and "no es válido" in response.text
        _assert_no_injection(response.text)


def test_the_pause_page_does_not_leak_the_token(web, make) -> None:  # noqa: F811
    token = pause_token("s", make.subscription().id)
    assert web.get("/pausar", params={"token": token}).headers["referrer-policy"] == "no-referrer"


# --- text from outside ---


def test_text_with_html_appears_as_text(web, db_session, make) -> None:  # noqa: F811
    _sign_up(web)
    user = db_session.query(Usuario).one()
    subscription = make.subscription(user, f"calle {EVIL}", filters={"provincia": {"tipo": "seleccion", "valor": EVIL}})
    make.match(subscription, make.document(f"La calle {EVIL}", titulo=f"T {EVIL}", notice_number=EVIL[:60], url_fuente="javascript:alert(1)"))
    token = pause_token("s", subscription.id)
    pages = {
        "inbox": web.get("/bandeja").text,
        "subscriptions": web.get("/suscripciones").text,
        "pause": web.get("/pausar", params={"token": token}).text,
        "results": web.get("/resultados", params={"q": EVIL, "mode": "all"}).text,
        "sign in": web.post("/ingresar", data={"email": EVIL, "password": "x"}).text,
        "next": web.get("/ingresar", params={"next": EVIL}).text,
        "registration": web.post("/registro", data={"email": EVIL, "password": "x"}).text,
    }
    for name, html in pages.items():
        _assert_no_injection(html)
        if name in ("inbox", "subscriptions", "pause", "sign in", "registration"):
            assert "&lt;script&gt;" in html, name


@pytest.mark.parametrize("query", ["zapatos", "obra", f"obra {EVIL}"], ids=["by meaning", "around", "inside"])
def test_the_excerpt_is_escaped_wherever_the_shared_words_are(web, db_session, make, query) -> None:  # noqa: F811
    _sign_up(web)
    make.match(make.subscription(db_session.query(Usuario).one(), query), make.document(f"Una obra {EVIL} y otra obra"))
    html = re.sub("</?mark>", "", web.get("/bandeja").text)
    _assert_no_injection(html)
    assert "&lt;script&gt;" in html


def test_a_search_result_is_escaped(web, db_session, make) -> None:  # noqa: F811
    document = make.document(f"Una obra {EVIL}", titulo=f"T {EVIL}", notice_number="7")
    document.fragmentos[0].embedding = FakeEmbeddingProvider().embed_passage("x")
    db_session.commit()
    html = web.get("/resultados", params={"q": "obra", "mode": "all"}).text
    _assert_no_injection(html)
    assert html.count("&lt;script&gt;") >= 2


def test_a_rating_of_a_search_with_quotes_works(web, db_session, make) -> None:  # noqa: F811
    import json

    document = make.document("Obra")
    document.fragmentos[0].embedding = FakeEmbeddingProvider().embed_passage("Obra")
    db_session.commit()
    page = web.get("/resultados", params={"q": 'la "obra" d\'agua', "mode": "all"}).text
    values = [json.loads(a["hx-vals"]) for t, a in _Tags(page).tags if "hx-vals" in a]
    assert values and values[0]["consulta"] == 'la "obra" d\'agua'
    assert web.post("/valorar", data=values[0]).status_code == 200


# --- the API behind ---


def test_the_address_of_the_visitor_reaches_the_api(web, api_calls) -> None:
    web.get("/", headers={"X-Forwarded-For": "6.6.6.6"})
    assert {c.headers["x-forwarded-for"] for c in api_calls} == {"testclient"}, "not what the visitor says"


@pytest.mark.parametrize(
    ("group", "call"),
    [
        ("search", lambda w: w.get("/resultados", params={"q": "x"})),
        ("login", lambda w: w.post("/ingresar", data={"email": "a@example.org", "password": "x"})),
        ("register", lambda w: w.post("/registro", data={"email": "x", "password": "x"})),
    ],
)
def test_too_many_requests_is_a_message_and_not_a_failure(web, monkeypatch, group, call) -> None:
    from src.api.rate_limit import limiter

    monkeypatch.setenv(f"RATE_LIMIT_{group.upper()}", "1/hour")
    limiter.reset()
    call(web)
    response = call(web)
    assert response.status_code in (200, 429) and "Demasiad" in response.text


def test_if_the_api_is_down_the_page_says_so(web, module, monkeypatch) -> None:
    @contextmanager
    def down(timeout: float = 10.0):
        class Client:
            def request(self, *args, **kwargs):
                raise httpx.ConnectError("refused")

        yield Client()

    monkeypatch.setattr(module, "backend_client", down)
    for path in ("/", "/ingresar", "/pausar?token=x", "/resultados?q=x"):
        response = web.get(path)
        assert response.status_code in (200, 503) and "no está disponible" in response.text, path


def test_every_field_has_a_label(web, db_session, make) -> None:  # noqa: F811
    _sign_up(web)
    make.match(make.subscription(db_session.query(Usuario).one()))
    for path in ("/", "/bandeja", "/suscripciones", "/ingresar", "/registro"):
        html = web.get(path).text
        tags = _Tags(html).tags
        labels = {a.get("for") for t, a in tags if t == "label"}
        for tag, attributes in tags:
            if tag in ("input", "select", "textarea") and attributes.get("type") not in ("hidden", "radio", "checkbox"):
                assert attributes.get("id") in labels, (path, attributes)
        ids = [a["id"] for _, a in tags if "id" in a]
        assert len(ids) == len(set(ids)), path
        assert html.count("<h1") == 1 and 'lang="es"' in html, path
