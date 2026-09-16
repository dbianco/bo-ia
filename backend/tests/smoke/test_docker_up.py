"""T017: smoke test end-to-end — levanta docker compose y ejercita la
búsqueda contra los datos de ejemplo (FR-016, FR-017, SC-006)."""
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_URL = "http://localhost:9102"
BACKEND_URL = "http://localhost:9101"


def _entorno_sin_database_url() -> dict[str, str]:
    """`docker compose` prioriza las variables de entorno del shell por
    sobre el `.env` del proyecto. Si quien corre los tests tiene
    DATABASE_URL exportada (para usar Alembic/pytest contra el puerto
    expuesto en el host), esa URL pisaría la interna (`db:5432`) que
    necesitan los contenedores. Se arma un entorno limpio para evitar
    justamente ese choque."""
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    return env


@pytest.mark.docker
def test_stack_levanta_con_un_comando_y_la_busqueda_funciona_con_datos_de_ejemplo() -> None:
    """FR-016: un solo comando levanta todo. FR-017: hay datos de ejemplo
    precargados. SC-006: el entorno arranca sano en ambas plataformas
    (acá se corre en la plataforma donde vive el runner de CI/dev)."""
    env = _entorno_sin_database_url()
    try:
        subprocess.run(
            ["docker", "compose", "up", "-d", "--build", "--wait"],
            cwd=REPO_ROOT,
            check=True,
            timeout=900,
            env=env,
        )
        assert httpx.get(f"{BACKEND_URL}/health", timeout=10).json() == {"status": "ok"}
        assert httpx.get(f"{WEB_URL}/health", timeout=10).json() == {"status": "ok"}

        # El seed corre en el startup del backend y puede tardar unos
        # segundos más que el healthcheck en terminar de generar embeddings.
        respuesta = None
        for _ in range(30):
            respuesta = httpx.get(
                f"{BACKEND_URL}/v1/search", params={"q": "presupuesto provincial"}, timeout=30
            )
            if respuesta.json().get("total", 0) > 0:
                break
            time.sleep(2)

        assert respuesta is not None
        cuerpo = respuesta.json()
        assert cuerpo["total"] > 0
        assert any("presupuesto" in r["texto"].lower() for r in cuerpo["resultados"])
    finally:
        subprocess.run(["docker", "compose", "down"], cwd=REPO_ROOT, check=True, env=env)
