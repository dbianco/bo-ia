"""runs: partial state and changed count

Revision ID: f7c2b9d4e6a1
Revises: e5a94f7b3d12
Create Date: 2026-10-01 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7c2b9d4e6a1"
down_revision: Union[str, Sequence[str], None] = "e5a94f7b3d12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("ejecuciones_fuente", sa.Column("changed", sa.Integer(), server_default="0", nullable=False))
    op.drop_constraint("ck_ejecucion_fuente_estado", "ejecuciones_fuente", type_="check")
    op.create_check_constraint(
        "ck_ejecucion_fuente_estado",
        "ejecuciones_fuente",
        "estado IN ('en_curso', 'completada', 'partial', 'fallida')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_ejecucion_fuente_estado", "ejecuciones_fuente", type_="check")
    # What the older code called a run with some failures.
    op.execute("UPDATE ejecuciones_fuente SET estado = 'completada' WHERE estado = 'partial'")
    op.create_check_constraint(
        "ck_ejecucion_fuente_estado", "ejecuciones_fuente", "estado IN ('en_curso', 'completada', 'fallida')"
    )
    op.drop_column("ejecuciones_fuente", "changed")
