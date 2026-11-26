"""explained alerts, outbox, digests and read state

Revision ID: a3d8e6c1b7f4
Revises: f7c2b9d4e6a1
Create Date: 2026-10-02 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3d8e6c1b7f4"
down_revision: Union[str, Sequence[str], None] = "f7c2b9d4e6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FREQUENCIES = "('immediate', 'daily', 'weekly')"


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "digests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estado", sa.String(16), server_default="pendiente", nullable=False),
        sa.Column("fecha_intento", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reintentos", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_proveedor", sa.Text(), nullable=True),
        _now("next_attempt_at"),
        _now("created_at"),
        sa.CheckConstraint("estado IN ('pendiente', 'entregada', 'fallida')", name="ck_digest_estado"),
        sa.CheckConstraint("frequency IN ('daily', 'weekly')", name="ck_digest_frequency"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("usuario_id", "frequency", "period_end", name="uq_digest_usuario_frequency_period"),
    )

    op.add_column("evaluaciones_match", sa.Column("fragmento_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "evaluaciones_match_fragmento_id_fkey", "evaluaciones_match", "fragmentos", ["fragmento_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_evaluaciones_match_fragmento_id", "evaluaciones_match", ["fragmento_id"])

    op.execute(
        "UPDATE suscripciones SET frecuencia_notificacion = 'immediate' "
        f"WHERE frecuencia_notificacion IS NULL OR frecuencia_notificacion NOT IN {FREQUENCIES}"
    )
    op.alter_column("suscripciones", "frecuencia_notificacion", server_default="immediate", nullable=False)
    op.create_check_constraint(
        "ck_suscripcion_frecuencia", "suscripciones", f"frecuencia_notificacion IN {FREQUENCIES}"
    )

    # An email left pending by an interruption was never going to be sent. The
    # outbox would send it now, perhaps months later.
    op.execute(
        "UPDATE entregas_notificacion SET estado = 'fallida', "
        "error_proveedor = 'Interrumpida antes de que hubiera reintentos' WHERE estado = 'pendiente'"
    )
    op.add_column(
        "entregas_notificacion", sa.Column("frequency", sa.String(16), server_default="immediate", nullable=False)
    )
    op.add_column("entregas_notificacion", sa.Column("digest_id", sa.Integer(), nullable=True))
    op.add_column("entregas_notificacion", _now("next_attempt_at"))
    op.add_column("entregas_notificacion", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_entrega_notificacion_frequency", "entregas_notificacion", f"frequency IN {FREQUENCIES}"
    )
    op.create_foreign_key(
        "entregas_notificacion_digest_id_fkey", "entregas_notificacion", "digests", ["digest_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_entregas_notificacion_digest_id", "entregas_notificacion", ["digest_id"])
    op.create_index(
        "ix_entregas_notificacion_pendientes", "entregas_notificacion", ["next_attempt_at"],
        postgresql_where=sa.text("estado = 'pendiente'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Emails still waiting are not sent by the older code: let them go out first.
    op.drop_index("ix_entregas_notificacion_pendientes", table_name="entregas_notificacion")
    op.drop_index("ix_entregas_notificacion_digest_id", table_name="entregas_notificacion")
    op.drop_constraint("entregas_notificacion_digest_id_fkey", "entregas_notificacion", type_="foreignkey")
    op.drop_constraint("ck_entrega_notificacion_frequency", "entregas_notificacion", type_="check")
    for name in ("read_at", "next_attempt_at", "digest_id", "frequency"):
        op.drop_column("entregas_notificacion", name)
    op.drop_constraint("ck_suscripcion_frecuencia", "suscripciones", type_="check")
    op.alter_column("suscripciones", "frecuencia_notificacion", server_default=None, nullable=True)
    op.drop_index("ix_evaluaciones_match_fragmento_id", table_name="evaluaciones_match")
    op.drop_constraint("evaluaciones_match_fragmento_id_fkey", "evaluaciones_match", type_="foreignkey")
    op.drop_column("evaluaciones_match", "fragmento_id")
    op.drop_table("digests")
