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
    # boletines, fragmentos, tags/fragmento_tags, valoraciones, texto_tsv,
    # generalización a documentos/fuentes (Etapa 1).
    for _ in range(6):
        command.downgrade(alembic_config, "-1")
    command.upgrade(alembic_config, "head")


def test_generalize_documentos_fuentes_preserva_datos_y_hace_backfill(alembic_config: Config) -> None:
    """SC-006: la migración de la Etapa 1 conserva los datos existentes y
    hace backfill de `fuentes` y `documentos.metadata` a partir de
    `jurisdiccion`, en el ciclo upgrade -> downgrade -> upgrade."""
    command.upgrade(alembic_config, "9aaa3783a1df")  # justo antes de la Etapa 1

    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO boletines "
            "(jurisdiccion, identificador_oficial, fecha_publicacion, texto_original, url_oficial, "
            "hash_contenido, estado_ingesta) "
            "VALUES ('cordoba', 'BO-MIG-001', '2026-01-01', 'texto de prueba', 'https://example.org/1', "
            "'hash-mig-001', 'completo') RETURNING id"
        )
        (boletin_id,) = cur.fetchone()
        cur.execute(
            "INSERT INTO fragmentos (boletin_id, posicion, texto, fecha_publicacion) "
            "VALUES (%s, 0, 'texto de prueba', '2026-01-01')",
            (boletin_id,),
        )

    command.upgrade(alembic_config, "head")

    with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT clave FROM fuentes")
        assert cur.fetchall() == [("cordoba",)]

        cur.execute(
            "SELECT identificador_externo, metadata, fuente_id FROM documentos WHERE id = %s", (boletin_id,)
        )
        identificador_externo, metadata, fuente_id = cur.fetchone()
        assert identificador_externo == "BO-MIG-001"
        assert metadata == {"provincia": "cordoba"}
        cur.execute("SELECT clave FROM fuentes WHERE id = %s", (fuente_id,))
        assert cur.fetchone() == ("cordoba",)

        cur.execute("SELECT documento_id, fecha FROM fragmentos WHERE documento_id = %s", (boletin_id,))
        assert cur.fetchone() == (boletin_id, __import__("datetime").date(2026, 1, 1))

    command.downgrade(alembic_config, "9aaa3783a1df")

    with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT jurisdiccion, identificador_oficial FROM boletines WHERE id = %s", (boletin_id,)
        )
        assert cur.fetchone() == ("cordoba", "BO-MIG-001")

    command.upgrade(alembic_config, "head")
