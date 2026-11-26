"""Rate limit of the endpoints that anybody can call, set by environment variables."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api import deps
from src.api.main import ROUTERS, app
from src.api.rate_limit import (
    DEFAULTS,
    GROUPS_BY_ROUTE,
    Limit,
    RateLimitConfigError,
    RateLimiter,
    client_address,
    limiter,
    load_limits,
    parse_limit,
)
from src.config.installation import InstallationConfig
from src.db.models import Usuario
from src.processor.embeddings import FakeEmbeddingProvider


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# --- the limiter itself ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("60/minute", Limit(60, 60)),
        ("5/hour", Limit(5, 3600)),
        (" 1 / second ", Limit(1, 1)),
        ("10/DAY", Limit(10, 86400)),
        ("off", None),
        ("OFF", None),
    ],
)
def test_reads_a_limit(text, expected) -> None:
    assert parse_limit(text) == expected


@pytest.mark.parametrize("text", ["60", "x/minute", "0/minute", "-1/minute", "5/week", "1.5/minute", "/minute", "unlimited"])
def test_a_wrong_limit_is_an_error(text) -> None:
    with pytest.raises(RateLimitConfigError):
        parse_limit(text)


def test_as_many_as_the_limit_at_once_and_then_one_by_one() -> None:
    clock = Clock()
    limits = RateLimiter({"g": Limit(6, 60)}, clock=clock)
    assert [limits.wait("g", "a") for _ in range(6)] == [0.0] * 6
    assert limits.wait("g", "a") == pytest.approx(10)
    clock.now += 9.9
    assert limits.wait("g", "a") == pytest.approx(0.1)
    clock.now += 0.2
    assert limits.wait("g", "a") == 0.0
    assert limits.wait("g", "a") > 9


def test_a_refused_request_does_not_make_the_wait_longer() -> None:
    clock = Clock()
    limits = RateLimiter({"g": Limit(1, 10)}, clock=clock)
    limits.wait("g", "a")
    for _ in range(50):
        assert limits.wait("g", "a") <= 10
    clock.now += 10.01
    assert limits.wait("g", "a") == 0.0


def test_no_more_than_twice_the_limit_in_any_period() -> None:
    """With a full burst and the steady rate after it."""
    clock = Clock()
    limits = RateLimiter({"g": Limit(10, 60)}, clock=clock)
    clock.now += 3600
    accepted = []
    for _ in range(2400):
        if limits.wait("g", "a") == 0.0:
            accepted.append(clock.now)
        clock.now += 0.1
    for start in accepted:
        assert sum(start <= t < start + 60 for t in accepted) <= 20


def test_addresses_and_groups_are_counted_apart() -> None:
    limits = RateLimiter({"g": Limit(1, 60), "h": Limit(1, 60)}, clock=Clock())
    assert [limits.wait("g", "a"), limits.wait("g", "b"), limits.wait("h", "a")] == [0.0, 0.0, 0.0]
    assert limits.wait("g", "a") > 0


def test_a_group_that_is_off_has_no_limit() -> None:
    limits = RateLimiter({"g": None}, clock=Clock())
    assert {limits.wait("g", "a") for _ in range(500)} == {0.0}


def test_memory_is_bounded() -> None:
    """Whoever changes address with each request must not fill the memory."""
    clock = Clock()
    limits = RateLimiter({"g": Limit(2, 60)}, clock=clock, max_addresses=100)
    for i in range(5000):
        limits.wait("g", f"address {i}")
    assert len(limits) <= 100


def test_threads_do_not_get_more_than_the_limit() -> None:
    from concurrent.futures import ThreadPoolExecutor

    limits = RateLimiter({"g": Limit(50, 3600)}, clock=Clock())
    with ThreadPoolExecutor(16) as pool:
        accepted = sum(w == 0.0 for w in pool.map(lambda _: limits.wait("g", "a"), range(1000)))
    assert accepted == 50


# --- configuration ---


def test_defaults_and_variables(monkeypatch) -> None:
    for group in DEFAULTS:
        monkeypatch.delenv(f"RATE_LIMIT_{group.upper()}", raising=False)
    assert load_limits() == {group: parse_limit(text) for group, text in DEFAULTS.items()}
    monkeypatch.setenv("RATE_LIMIT_SEARCH", "7/second")
    monkeypatch.setenv("RATE_LIMIT_RATINGS", "off")
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "")  # what compose passes when it is not set
    limits = load_limits()
    assert limits["search"] == Limit(7, 1) and limits["ratings"] is None
    assert limits["login"] == parse_limit(DEFAULTS["login"])


def test_a_wrong_variable_names_itself(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_SEARCH", "many")
    with pytest.raises(RateLimitConfigError, match="RATE_LIMIT_SEARCH"):
        load_limits()


def test_a_wrong_variable_stops_startup(db_session: Session, monkeypatch) -> None:
    from src.api import main

    monkeypatch.setattr(main, "get_installation_config", lambda: InstallationConfig(nombre="x", seed=False))
    monkeypatch.setattr(main.deps, "_engine", lambda: db_session.get_bind())
    monkeypatch.setattr(main, "get_embedder", lambda: None)
    monkeypatch.setenv("RATE_LIMIT_SEARCH", "many")
    with pytest.raises(RateLimitConfigError), TestClient(main.app):
        pass


# --- who is calling ---


@pytest.mark.parametrize(
    ("peer", "forwarded", "trusted", "expected"),
    [
        ("203.0.113.9", None, "", "203.0.113.9"),
        ("203.0.113.9", "1.2.3.4", "", "203.0.113.9"),
        ("203.0.113.9", "1.2.3.4", "10.0.0.0/8", "203.0.113.9"),
        ("10.0.0.5", "1.2.3.4", "10.0.0.0/8", "1.2.3.4"),
        ("10.0.0.5", "1.2.3.4", "10.0.0.5", "1.2.3.4"),
        ("10.0.0.5", None, "10.0.0.5", "10.0.0.5"),
        ("10.0.0.5", "", "10.0.0.5", "10.0.0.5"),
        ("10.0.0.5", "spoofed, 1.2.3.4", "10.0.0.5", "1.2.3.4"),
        ("10.0.0.5", "6.6.6.6, 1.2.3.4, 10.0.0.7", "10.0.0.0/8", "1.2.3.4"),
        ("10.0.0.5", "not an address", "10.0.0.5", "10.0.0.5"),
        ("10.0.0.5", "1.2.3.4:5678", "10.0.0.5", "1.2.3.4"),
        ("10.0.0.5", "[2001:db8::1]:443", "10.0.0.5", "2001:db8::/64"),
        ("2001:db8:0:1:aaaa::1", None, "", "2001:db8:0:1::/64"),
        ("::ffff:203.0.113.9", None, "", "203.0.113.9"),
        ("testclient", None, "", "testclient"),
        (None, "1.2.3.4", "", "unknown"),
    ],
)
def test_the_address_of_the_caller(peer, forwarded, trusted, expected) -> None:
    assert client_address(peer, forwarded, trusted) == expected


def test_a_proxy_may_be_trusted_by_name() -> None:
    """In Docker, the web has a name and an address that changes."""
    names = {"web": {"172.18.0.4"}}
    resolve = lambda name: names.get(name, set())  # noqa: E731
    assert client_address("172.18.0.4", "1.2.3.4", "web", resolve=resolve) == "1.2.3.4"
    assert client_address("172.18.0.1", "1.2.3.4", "web", resolve=resolve) == "172.18.0.1", "another container, or the host"
    assert client_address("172.18.0.4", "1.2.3.4", "nothing", resolve=resolve) == "172.18.0.4"


def test_a_name_that_does_not_resolve_is_not_trusted() -> None:
    from src.api.rate_limit import resolve_name

    assert resolve_name("this-name-does-not-exist.invalid") == set()


# --- the endpoints ---


@pytest.fixture()
def client(db_session: Session, monkeypatch):
    for group in DEFAULTS:
        monkeypatch.setenv(f"RATE_LIMIT_{group.upper()}", "3/hour")
    limiter.reset()

    def session():
        yield db_session

    app.dependency_overrides[deps.get_session] = session
    app.dependency_overrides[deps.get_embedder] = lambda: FakeEmbeddingProvider()
    app.dependency_overrides[deps.get_installation_config] = lambda: InstallationConfig(nombre="x")
    yield TestClient(app)
    app.dependency_overrides.clear()


CALLS = {
    "search": ("GET", "/v1/search?q=x", None),
    "ratings": ("POST", "/v1/valoraciones", {"fragmento_id": 1, "consulta": "x", "valor": "positivo"}),
    "register": ("POST", "/v1/auth/registro", {"email": "a@example.org", "password": "una-contraseña-larga"}),
    "login": ("POST", "/v1/auth/login", {"email": "a@example.org", "password": "incorrecta"}),
    "public": ("GET", "/v1/config", None),
}


@pytest.mark.parametrize("group", CALLS)
def test_the_fourth_call_is_refused(client: TestClient, group) -> None:
    method, path, body = CALLS[group]
    for _ in range(3):
        assert client.request(method, path, json=body).status_code != 429
    response = client.request(method, path, json=body)
    assert response.status_code == 429
    assert 0 < int(response.headers["retry-after"]) <= 1200
    assert "detail" in response.json()


def test_a_refused_call_does_nothing(client: TestClient, db_session: Session) -> None:
    for i in range(6):
        client.post("/v1/auth/registro", json={"email": f"u{i}@example.org", "password": "una-contraseña-larga"})
    assert db_session.scalar(select(func.count()).select_from(Usuario)) == 3


def test_calls_that_are_not_valid_count_too(client: TestClient) -> None:
    for _ in range(3):
        assert client.post("/v1/auth/login", json={}).status_code == 422
    assert client.post("/v1/auth/login", json={}).status_code == 429


def test_visitors_of_the_web_are_counted_apart(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", "10.1.1.1")
    web = TestClient(app, client=("10.1.1.1", 1234))
    for visitor in ("1.1.1.1", "2.2.2.2"):
        for _ in range(3):
            assert web.get("/v1/config", headers={"X-Forwarded-For": visitor}).status_code == 200
        assert web.get("/v1/config", headers={"X-Forwarded-For": visitor}).status_code == 429


def test_nobody_gets_more_by_forging_the_header(client: TestClient) -> None:
    codes = [client.get("/v1/config", headers={"X-Forwarded-For": f"9.9.9.{i}"}).status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_the_health_check_and_the_endpoints_of_a_user_have_no_limit(client: TestClient) -> None:
    assert {client.get("/health").status_code for _ in range(20)} == {200}
    assert {client.get("/v1/suscripciones").status_code for _ in range(20)} == {401}


def test_with_everything_off_nothing_is_refused(client: TestClient, monkeypatch) -> None:
    for group in DEFAULTS:
        monkeypatch.setenv(f"RATE_LIMIT_{group.upper()}", "off")
    limiter.reset()
    assert {client.get("/v1/config").status_code for _ in range(50)} == {200}


def test_every_route_that_anybody_can_call_has_a_limit() -> None:
    """A new public route has to be given a group, or to require who calls it."""
    from src.api.deps import get_usuario_actual
    from src.auth.operator import require_operator

    def calls(dependant) -> set:
        return {dependant.call} | {c for d in dependant.dependencies for c in calls(d)}

    public = {
        (method, route.path)
        for router in ROUTERS
        for route in router.routes
        if not calls(route.dependant) & {get_usuario_actual, require_operator}
        for method in route.methods
    }
    assert public == set(GROUPS_BY_ROUTE)
    assert set(GROUPS_BY_ROUTE.values()) == set(DEFAULTS)
