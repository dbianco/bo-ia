"""notice segmentation: issue, number and pages; content hash unique per date

Revision ID: c4d7e1f0a2b3
Revises: 5254089ba99e
Create Date: 2026-09-28 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d7e1f0a2b3"
down_revision: Union[str, Sequence[str], None] = "5254089ba99e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("documentos", sa.Column("issue", sa.String(128), nullable=True))
    op.add_column("documentos", sa.Column("notice_number", sa.String(64), nullable=True))
    op.add_column("documentos", sa.Column("first_page", sa.Integer(), nullable=True))
    op.add_column("documentos", sa.Column("last_page", sa.Integer(), nullable=True))
    op.add_column("fragmentos", sa.Column("page", sa.Integer(), nullable=True))
    op.create_index("ix_documentos_fuente_id_issue", "documentos", ["fuente_id", "issue"])
    op.drop_constraint("uq_documento_hash_contenido", "documentos", type_="unique")
    op.create_unique_constraint("uq_documento_hash_contenido_fecha", "documentos", ["hash_contenido", "fecha"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_documento_hash_contenido_fecha", "documentos", type_="unique")
    # One text may now be stored once per date. The first copy keeps its hash and
    # the others get a derived one: the old constraint holds and no row is lost.
    op.execute(
        """
        UPDATE documentos d
        SET hash_contenido = encode(sha256(convert_to(d.hash_contenido || ':' || d.id, 'UTF8')), 'hex')
        FROM (
            SELECT id, row_number() OVER (PARTITION BY hash_contenido ORDER BY fecha, id) AS copy FROM documentos
        ) ranked
        WHERE ranked.id = d.id AND ranked.copy > 1
        """
    )
    op.create_unique_constraint("uq_documento_hash_contenido", "documentos", ["hash_contenido"])
    op.drop_index("ix_documentos_fuente_id_issue", table_name="documentos")
    op.drop_column("fragmentos", "page")
    op.drop_column("documentos", "last_page")
    op.drop_column("documentos", "first_page")
    op.drop_column("documentos", "notice_number")
    op.drop_column("documentos", "issue")
