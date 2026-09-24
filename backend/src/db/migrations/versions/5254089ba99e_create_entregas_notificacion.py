"""create entregas_notificacion

Etapa 4 (notificaciones, ver sección 4.6 de
docs/superpowers/specs/2026-09-18-plataforma-tematica-reutilizable-design.md).

Revision ID: 5254089ba99e
Revises: 561281315b74
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5254089ba99e'
down_revision: Union[str, Sequence[str], None] = '561281315b74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "entregas_notificacion",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "match_id",
            sa.Integer(),
            sa.ForeignKey("evaluaciones_match.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("canal", sa.String(length=16), nullable=False),
        sa.Column("estado", sa.String(length=16), nullable=False, server_default="pendiente"),
        sa.Column("fecha_intento", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reintentos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_proveedor", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("canal IN ('bandeja', 'correo')", name="ck_entrega_notificacion_canal"),
        sa.CheckConstraint(
            "estado IN ('pendiente', 'entregada', 'fallida')", name="ck_entrega_notificacion_estado"
        ),
        sa.UniqueConstraint("match_id", "canal", name="uq_entrega_notificacion_match_canal"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("entregas_notificacion")
