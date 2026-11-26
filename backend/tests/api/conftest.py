"""The tests of the search API run on both implementations: the response does
not depend on which one answers."""
import pytest

from src.api.deps import get_search_backend
from src.api.main import app
from src.engine.backend import EngineBackend, PostgresBackend

ON_BOTH = {"test_search", "test_search_filters", "test_search_hybrid", "test_search_recall", "test_notices"}


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if metafunc.module.__name__.rsplit(".", 1)[-1] in ON_BOTH:
        metafunc.fixturenames.append("search_backend")
        metafunc.parametrize("search_backend", ["postgres", "engine"], indirect=True)


@pytest.fixture()
def search_backend(request: pytest.FixtureRequest):
    backend = PostgresBackend() if request.param == "postgres" else EngineBackend()
    app.dependency_overrides[get_search_backend] = lambda: backend
    yield backend
    app.dependency_overrides.pop(get_search_backend, None)
