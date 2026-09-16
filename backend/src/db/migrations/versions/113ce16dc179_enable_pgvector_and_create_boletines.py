"""enable pgvector and create boletines

Revision ID: 113ce16dc179
Revises: 
Create Date: 2026-09-16 16:27:50.332675

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '113ce16dc179'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "boletines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("jurisdiccion", sa.String(length=64), nullable=False),
        sa.Column("identificador_oficial", sa.String(length=128), nullable=False),
        sa.Column("fecha_publicacion", sa.Date(), nullable=False),
        sa.Column("titulo", sa.Text(), nullable=True),
        sa.Column("texto_original", sa.Text(), nullable=False),
        sa.Column("url_oficial", sa.Text(), nullable=False),
        sa.Column("hash_contenido", sa.String(length=64), nullable=False),
        sa.Column("estado_ingesta", sa.String(length=32), nullable=False, server_default="completo"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("jurisdiccion", "identificador_oficial", name="uq_boletin_identificador"),
        sa.UniqueConstraint("hash_contenido", name="uq_boletin_hash_contenido"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("boletines")
    op.execute("DROP EXTENSION IF EXISTS vector")
