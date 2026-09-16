"""T011: verifica que cada migración tiene un downgrade que funciona.

Corre contra una base de datos de test separada (`bo_ia_test`), creada y
destruida en cada corrida, para no tocar los datos de desarrollo.
"""
import os
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[1]
ADMIN_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://bo_ia:dev_only_change_me@localhost:9100/bo_ia"
)
TEST_DB_NAME = "bo_ia_test"


def _admin_dsn() -> str:
    # Conexión psycopg "pura" (sin el prefijo +psycopg de SQLAlchemy) a la
    # base de mantenimiento, para poder crear/borrar la base de test.
    plain = ADMIN_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    return plain.rsplit("/", 1)[0] + "/postgres"


def _test_database_url() -> str:
    base = ADMIN_DATABASE_URL.rsplit("/", 1)[0]
    return f"{base}/{TEST_DB_NAME}"


@pytest.fixture()
def alembic_config() -> Config:
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")
            cur.execute(f"CREATE DATABASE {TEST_DB_NAME}")

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _test_database_url()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "src/db/migrations"))

    yield cfg

    if previous is not None:
        os.environ["DATABASE_URL"] = previous
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")


def test_upgrade_head_then_full_downgrade_then_upgrade_again(alembic_config: Config) -> None:
    """Cada `up` debe tener un `down` funcional (constitución de la compañía)."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")


def test_each_revision_downgrades_one_step_cleanly(alembic_config: Config) -> None:
    """Cada revisión individual puede bajar un paso y volver a subir sin error."""
    command.upgrade(alembic_config, "head")
    for _ in range(4):  # boletines, fragmentos, tags/fragmento_tags, valoraciones
        command.downgrade(alembic_config, "-1")
    command.upgrade(alembic_config, "head")
