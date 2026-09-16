"""create valoraciones

Revision ID: 7b248b8b4274
Revises: 20e22678f33f
Create Date: 2026-09-16 16:27:50.880128

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b248b8b4274'
down_revision: Union[str, Sequence[str], None] = '20e22678f33f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


VALORES_FEEDBACK = ("positivo", "negativo")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "valoraciones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fragmento_id",
            sa.Integer(),
            sa.ForeignKey("fragmentos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("consulta", sa.Text(), nullable=False),
        sa.Column("valor", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"valor IN {VALORES_FEEDBACK}", name="ck_valoracion_valor"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("valoraciones")
