"""generalize boletines to documentos, add fuentes

Etapa 1 del plan de generalización (ver sección 8 de
docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md):
- crea `fuentes`, con backfill desde los valores distintos de `jurisdiccion`.
- renombra `boletines` -> `documentos` y sus columnas al vocabulario
  genérico; agrega `fuente_id`, `metadata` (JSONB + índice GIN) y
  `version_ingesta`.
- renombra `fragmentos.boletin_id` -> `documento_id` y
  `fragmentos.fecha_publicacion` -> `fecha`.

Revision ID: a00b1eb51d18
Revises: 9aaa3783a1df
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a00b1eb51d18'
down_revision: Union[str, Sequence[str], None] = '9aaa3783a1df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "fuentes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clave", sa.String(length=128), nullable=False, unique=True),
        sa.Column("nombre", sa.String(length=256), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # Backfill: cada jurisdiccion distinta se vuelve una fuente propia.
    op.execute(
        "INSERT INTO fuentes (clave, nombre, config) "
        "SELECT DISTINCT jurisdiccion, jurisdiccion, '{}'::jsonb FROM boletines"
    )

    op.rename_table("boletines", "documentos")

    op.add_column("documentos", sa.Column("fuente_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE documentos SET fuente_id = fuentes.id "
        "FROM fuentes WHERE fuentes.clave = documentos.jurisdiccion"
    )
    op.alter_column("documentos", "fuente_id", nullable=False)
    op.create_foreign_key("fk_documento_fuente", "documentos", "fuentes", ["fuente_id"], ["id"])

    op.add_column(
        "documentos", sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}")
    )
    # Preserva la jurisdiccion original como metadata.provincia antes de
    # eliminar la columna: en el corpus del MVP, jurisdiccion era siempre
    # el nombre de una provincia.
    op.execute("UPDATE documentos SET metadata = jsonb_build_object('provincia', jurisdiccion)")

    op.execute("ALTER TABLE documentos DROP CONSTRAINT uq_boletin_identificador")
    op.drop_column("documentos", "jurisdiccion")

    op.alter_column("documentos", "identificador_oficial", new_column_name="identificador_externo")
    op.alter_column("documentos", "fecha_publicacion", new_column_name="fecha")
    op.alter_column("documentos", "texto_original", new_column_name="texto")
    op.alter_column("documentos", "url_oficial", new_column_name="url_fuente")
    op.alter_column("documentos", "estado_ingesta", new_column_name="estado")

    op.execute("ALTER TABLE documentos RENAME CONSTRAINT uq_boletin_hash_contenido TO uq_documento_hash_contenido")
    op.create_unique_constraint(
        "uq_documento_fuente_identificador", "documentos", ["fuente_id", "identificador_externo"]
    )

    op.add_column(
        "documentos",
        sa.Column("version_ingesta", sa.String(length=32), nullable=False, server_default="v1"),
    )
    op.create_index("ix_documentos_metadata_gin", "documentos", ["metadata"], postgresql_using="gin")

    op.alter_column("fragmentos", "boletin_id", new_column_name="documento_id")
    op.execute(
        "ALTER TABLE fragmentos RENAME CONSTRAINT uq_fragmento_boletin_posicion "
        "TO uq_fragmento_documento_posicion"
    )
    op.alter_column("fragmentos", "fecha_publicacion", new_column_name="fecha")
    op.execute("ALTER INDEX ix_fragmentos_fecha_publicacion RENAME TO ix_fragmentos_fecha")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER INDEX ix_fragmentos_fecha RENAME TO ix_fragmentos_fecha_publicacion")
    op.alter_column("fragmentos", "fecha", new_column_name="fecha_publicacion")
    op.execute(
        "ALTER TABLE fragmentos RENAME CONSTRAINT uq_fragmento_documento_posicion "
        "TO uq_fragmento_boletin_posicion"
    )
    op.alter_column("fragmentos", "documento_id", new_column_name="boletin_id")

    op.drop_index("ix_documentos_metadata_gin", table_name="documentos")
    op.drop_column("documentos", "version_ingesta")

    op.drop_constraint("uq_documento_fuente_identificador", "documentos", type_="unique")
    op.execute("ALTER TABLE documentos RENAME CONSTRAINT uq_documento_hash_contenido TO uq_boletin_hash_contenido")

    op.alter_column("documentos", "estado", new_column_name="estado_ingesta")
    op.alter_column("documentos", "url_fuente", new_column_name="url_oficial")
    op.alter_column("documentos", "texto", new_column_name="texto_original")
    op.alter_column("documentos", "fecha", new_column_name="fecha_publicacion")
    op.alter_column("documentos", "identificador_externo", new_column_name="identificador_oficial")

    op.add_column("documentos", sa.Column("jurisdiccion", sa.String(length=64), nullable=True))
    op.execute(
        "UPDATE documentos SET jurisdiccion = COALESCE("
        "metadata->>'provincia', (SELECT clave FROM fuentes WHERE fuentes.id = documentos.fuente_id))"
    )
    op.alter_column("documentos", "jurisdiccion", nullable=False)
    op.create_unique_constraint(
        "uq_boletin_identificador", "documentos", ["jurisdiccion", "identificador_oficial"]
    )

    op.drop_column("documentos", "metadata")
    op.drop_constraint("fk_documento_fuente", "documentos", type_="foreignkey")
    op.drop_column("documentos", "fuente_id")

    op.rename_table("documentos", "boletines")
    op.drop_table("fuentes")
