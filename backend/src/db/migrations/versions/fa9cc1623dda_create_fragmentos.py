"""create fragmentos

Revision ID: fa9cc1623dda
Revises: 113ce16dc179
Create Date: 2026-09-16 16:27:50.525992

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = 'fa9cc1623dda'
down_revision: Union[str, Sequence[str], None] = '113ce16dc179'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EMBEDDING_DIM = 1024  # Qwen/Qwen3-Embedding-0.6B


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "fragmentos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "boletin_id",
            sa.Integer(),
            sa.ForeignKey("boletines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("posicion", sa.Integer(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        # REQ-05: cada fragmento conserva su propia fecha_publicacion,
        # denormalizada desde boletines, para no depender de un join en el
        # filtro de fecha de la búsqueda (REQ-09).
        sa.Column("fecha_publicacion", sa.Date(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("boletin_id", "posicion", name="uq_fragmento_boletin_posicion"),
    )
    op.create_index(
        "ix_fragmentos_fecha_publicacion", "fragmentos", ["fecha_publicacion"]
    )
    # Índice HNSW para similitud coseno (REQ-10, REQ-15). Se construye igual
    # con la tabla vacía; con pocos fragmentos en el MVP el costo es mínimo.
    op.execute(
        "CREATE INDEX ix_fragmentos_embedding_hnsw ON fragmentos "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_fragmentos_embedding_hnsw")
    op.drop_index("ix_fragmentos_fecha_publicacion", table_name="fragmentos")
    op.drop_table("fragmentos")
