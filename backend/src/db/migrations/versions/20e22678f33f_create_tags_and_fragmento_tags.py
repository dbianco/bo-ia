"""create tags and fragmento_tags

Revision ID: 20e22678f33f
Revises: fa9cc1623dda
Create Date: 2026-09-16 16:27:50.711054

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20e22678f33f'
down_revision: Union[str, Sequence[str], None] = 'fa9cc1623dda'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ORIGENES_TAG = ("manual", "modelo", "sugerido")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("codigo", sa.String(length=64), nullable=False, unique=True),
        sa.Column("nombre", sa.String(length=128), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_table(
        "fragmento_tags",
        sa.Column(
            "fragmento_id",
            sa.Integer(),
            sa.ForeignKey("fragmentos.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("origen", sa.String(length=16), nullable=False),
        sa.Column("confianza", sa.Float(), nullable=True),
        sa.Column("modelo_version", sa.String(length=64), nullable=True),
        sa.Column("revisado_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"origen IN {ORIGENES_TAG}", name="ck_fragmento_tag_origen"),
        sa.CheckConstraint(
            "confianza IS NULL OR (confianza >= 0 AND confianza <= 1)",
            name="ck_fragmento_tag_confianza_rango",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("fragmento_tags")
    op.drop_table("tags")
