"""change tracking of documents, for the in-process search engine

Revision ID: e5a94f7b3d12
Revises: d81b6a2c9e47
Create Date: 2026-09-30 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5a94f7b3d12"
down_revision: Union[str, Sequence[str], None] = "d81b6a2c9e47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FRAGMENT_EVENTS = (
    ("insert", "INSERT", "NEW TABLE AS changed"),
    ("update", "UPDATE", "NEW TABLE AS changed"),
    ("delete", "DELETE", "OLD TABLE AS changed"),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "documentos",
        sa.Column(
            "changed_xid", sa.BigInteger(), server_default=sa.text("pg_current_xact_id()::text::bigint"), nullable=False
        ),
    )
    op.create_index("ix_documentos_changed_xid", "documentos", ["changed_xid"])
    op.execute(
        """
        CREATE FUNCTION documentos_track_changes() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.changed_xid := pg_current_xact_id()::text::bigint;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER documentos_track_changes BEFORE UPDATE ON documentos "
        "FOR EACH ROW EXECUTE FUNCTION documentos_track_changes()"
    )
    # Once per statement: a document has many fragments.
    op.execute(
        """
        CREATE FUNCTION fragmentos_track_changes() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE documentos SET changed_xid = pg_current_xact_id()::text::bigint
            WHERE id IN (SELECT DISTINCT documento_id FROM changed)
              AND changed_xid <> pg_current_xact_id()::text::bigint;
            RETURN NULL;
        END
        $$
        """
    )
    for name, event, table in FRAGMENT_EVENTS:
        op.execute(
            f"CREATE TRIGGER fragmentos_track_{name} AFTER {event} ON fragmentos "
            f"REFERENCING {table} FOR EACH STATEMENT EXECUTE FUNCTION fragmentos_track_changes()"
        )


def downgrade() -> None:
    """Downgrade schema."""
    for name, _, _ in FRAGMENT_EVENTS:
        op.execute(f"DROP TRIGGER fragmentos_track_{name} ON fragmentos")
    op.execute("DROP FUNCTION fragmentos_track_changes()")
    op.execute("DROP TRIGGER documentos_track_changes ON documentos")
    op.execute("DROP FUNCTION documentos_track_changes()")
    op.drop_index("ix_documentos_changed_xid", table_name="documentos")
    op.drop_column("documentos", "changed_xid")
