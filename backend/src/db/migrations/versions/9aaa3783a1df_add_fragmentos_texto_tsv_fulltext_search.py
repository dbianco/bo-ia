"""add fragmentos texto_tsv fulltext search

Revision ID: 9aaa3783a1df
Revises: 7b248b8b4274
Create Date: 2026-09-16 17:17:59.232313

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9aaa3783a1df'
down_revision: Union[str, Sequence[str], None] = '7b248b8b4274'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE fragmentos ADD COLUMN texto_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('spanish', texto)) STORED"
    )
    op.create_index(
        "ix_fragmentos_texto_tsv_gin", "fragmentos", ["texto_tsv"], postgresql_using="gin"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_fragmentos_texto_tsv_gin", table_name="fragmentos")
    op.execute("ALTER TABLE fragmentos DROP COLUMN texto_tsv")
