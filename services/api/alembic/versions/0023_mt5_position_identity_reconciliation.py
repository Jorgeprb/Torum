"""persist MT5 position identifiers for reliable close reconciliation

Revision ID: 0023_mt5_position_identity
Revises: 0022_strategy_workbench
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_mt5_position_identity"
down_revision: str | None = "0022_strategy_workbench"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("positions", sa.Column("mt5_position_identifier", sa.BigInteger(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE positions SET mt5_position_identifier = mt5_position_ticket "
            "WHERE mt5_position_identifier IS NULL AND mt5_position_ticket IS NOT NULL"
        )
    )
    op.create_index(
        "ix_positions_mt5_position_identifier",
        "positions",
        ["mt5_position_identifier"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_positions_mt5_position_identifier", table_name="positions")
    op.drop_column("positions", "mt5_position_identifier")
