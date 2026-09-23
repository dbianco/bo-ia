"""create ejecuciones_fuente

Etapa 2 (ingesta operativa, ver sección 4.4 de
docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md):
registra cada corrida de un conector sobre una fuente.

Revision ID: beff2319f387
Revises: a00b1eb51d18
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'beff2319f387'
down_revision: Union[str, Sequence[str], None] = 'a00b1eb51d18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ejecuciones_fuente",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fuente_id", sa.Integer(), sa.ForeignKey("fuentes.id"), nullable=False),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fin", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estado", sa.String(length=32), nullable=False),
        sa.Column("descubiertos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nuevos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("existentes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errores", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version_conector", sa.String(length=64), nullable=False),
        sa.Column("detalle_errores", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "estado IN ('en_curso', 'completada', 'fallida')", name="ck_ejecucion_fuente_estado"
        ),
    )
    op.create_index(
        "ix_ejecuciones_fuente_fuente_id_inicio", "ejecuciones_fuente", ["fuente_id", "inicio"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_ejecuciones_fuente_fuente_id_inicio", table_name="ejecuciones_fuente")
    op.drop_table("ejecuciones_fuente")
