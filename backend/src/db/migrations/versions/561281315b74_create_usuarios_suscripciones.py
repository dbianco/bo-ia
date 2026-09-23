"""create usuarios, sesiones, suscripciones, evaluaciones_match

Etapa 3 (clientes y suscripciones, ver sección 4.5 de
docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md).

Revision ID: 561281315b74
Revises: beff2319f387
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '561281315b74'
down_revision: Union[str, Sequence[str], None] = 'beff2319f387'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1024  # Qwen/Qwen3-Embedding-0.6B


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=256), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "sesiones",
        sa.Column("token", sa.String(length=64), primary_key=True),
        sa.Column(
            "usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "suscripciones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("texto_busqueda", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("filtros", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("estado", sa.String(length=16), nullable=False, server_default="activa"),
        sa.Column("canales", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("frecuencia_notificacion", sa.String(length=32), nullable=True),
        sa.Column("ultima_evaluacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("estado IN ('activa', 'pausada')", name="ck_suscripcion_estado"),
    )

    op.create_table(
        "evaluaciones_match",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "documento_id", sa.Integer(), sa.ForeignKey("documentos.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "suscripcion_id",
            sa.Integer(),
            sa.ForeignKey("suscripciones.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("filtros_aplicados", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("fecha_evaluacion", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "documento_id", "suscripcion_id", name="uq_evaluacion_match_documento_suscripcion"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("evaluaciones_match")
    op.drop_table("suscripciones")
    op.drop_table("sesiones")
    op.drop_table("usuarios")
