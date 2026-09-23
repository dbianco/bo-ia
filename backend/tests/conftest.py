"""Fixtures compartidos: una base de datos de test con el esquema aplicado."""
import os
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
ADMIN_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://bo_ia:dev_only_change_me@localhost:9100/bo_ia"
)
TEST_DB_NAME = "bo_ia_test"


def _admin_dsn() -> str:
    plain = ADMIN_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    return plain.rsplit("/", 1)[0] + "/postgres"


def _test_database_url() -> str:
    return ADMIN_DATABASE_URL.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")
        cur.execute(f"CREATE DATABASE {TEST_DB_NAME}")

    url = _test_database_url()
    os.environ["DATABASE_URL"] = url
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "src/db/migrations"))
    command.upgrade(cfg, "head")

    yield url

    os.environ["DATABASE_URL"] = ADMIN_DATABASE_URL
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")


def _truncar_tablas(database_url: str) -> None:
    """Limpia todas las tablas de datos en una conexión aparte, con
    autocommit. Necesario porque el código bajo test puede hacer sus
    propios `commit()` (ver FR-006 en el endpoint de ingesta), así que un
    simple `session.rollback()` no alcanza para aislar tests entre sí."""
    plain = database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(plain, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE TABLE valoraciones, fragmento_tags, fragmentos, tags, documentos, fuentes "
            "RESTART IDENTITY CASCADE"
        )


@pytest.fixture()
def db_session(test_database_url: str) -> Session:
    engine = create_engine(test_database_url)
    session_local = sessionmaker(bind=engine)
    session = session_local()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()
        _truncar_tablas(test_database_url)
