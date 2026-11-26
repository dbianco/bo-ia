"""asynchronous matching: queue, state and change tracking of subscriptions

Revision ID: d81b6a2c9e47
Revises: c4d7e1f0a2b3
Create Date: 2026-09-29 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d81b6a2c9e47"
down_revision: Union[str, Sequence[str], None] = "c4d7e1f0a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "matching_state",
        sa.Column("id", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_matching_state_one_row"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "matching_queue",
        sa.Column("documento_id", sa.Integer(), nullable=False),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["documento_id"], ["documentos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("documento_id"),
    )
    op.create_index("ix_matching_queue_next_attempt_at", "matching_queue", ["next_attempt_at"])

    op.add_column(
        "suscripciones",
        sa.Column("active_since", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False),
    )
    # The ones that exist have been active since before now: what is known about
    # them is the value that was stored, until the next document is matched.
    op.execute("UPDATE suscripciones SET active_since = created_at")
    op.add_column(
        "suscripciones",
        sa.Column(
            "changed_xid", sa.BigInteger(), server_default=sa.text("pg_current_xact_id()::text::bigint"), nullable=False
        ),
    )
    op.create_index("ix_suscripciones_changed_xid", "suscripciones", ["changed_xid"])
    op.execute(
        """
        CREATE FUNCTION suscripciones_track_changes() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            last_run timestamptz;
        BEGIN
            IF NEW.estado IS DISTINCT FROM OLD.estado
               OR NEW.filtros IS DISTINCT FROM OLD.filtros
               OR NEW.embedding IS DISTINCT FROM OLD.embedding THEN
                NEW.changed_xid := pg_current_xact_id()::text::bigint;
            END IF;
            IF OLD.estado = 'activa' AND NEW.estado <> 'activa' THEN
                SELECT last_run_at INTO last_run FROM matching_state;
                IF last_run >= OLD.active_since THEN
                    NEW.ultima_evaluacion := last_run;
                END IF;
            ELSIF OLD.estado <> 'activa' AND NEW.estado = 'activa' THEN
                NEW.active_since := clock_timestamp();
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER suscripciones_track_changes BEFORE UPDATE ON suscripciones "
        "FOR EACH ROW EXECUTE FUNCTION suscripciones_track_changes()"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER suscripciones_track_changes ON suscripciones")
    op.execute("DROP FUNCTION suscripciones_track_changes()")
    # The older code keeps the last evaluation in the row.
    op.execute(
        "UPDATE suscripciones SET ultima_evaluacion = s.last_run_at FROM matching_state s "
        "WHERE estado = 'activa' AND s.last_run_at >= active_since"
    )
    op.drop_index("ix_suscripciones_changed_xid", table_name="suscripciones")
    op.drop_column("suscripciones", "changed_xid")
    op.drop_column("suscripciones", "active_since")
    # Documents still in the queue were never matched: the older code has no way
    # to do it later, so they are lost for alerts. Let the queue drain first.
    op.drop_index("ix_matching_queue_next_attempt_at", table_name="matching_queue")
    op.drop_table("matching_queue")
    op.drop_table("matching_state")
