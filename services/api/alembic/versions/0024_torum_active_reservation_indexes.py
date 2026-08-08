"""index active Torum reservations used during order execution

Revision ID: 0024_torum_reservation_indexes
Revises: 0023_mt5_position_identity
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024_torum_reservation_indexes"
down_revision: str | None = "0023_mt5_position_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Partial indexes keep this migration compact even when strategy_signals
    # already contains millions of historical diagnostic rows.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_orders_torum_active_reservations
        ON orders (internal_symbol, user_id, created_at)
        WHERE source = 'STRATEGY'
          AND strategy_key = 'torum_v1'
          AND status IN ('CREATED', 'VALIDATING', 'SENT')
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_strategy_signals_torum_active_reservations
        ON strategy_signals (internal_symbol, user_id, created_at)
        WHERE strategy_key = 'torum_v1'
          AND signal_type = 'ENTRY'
          AND side = 'BUY'
          AND status IN ('RISK_APPROVED', 'SENT_TO_ORDER_MANAGER')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_strategy_signals_torum_active_reservations")
    op.execute("DROP INDEX IF EXISTS ix_orders_torum_active_reservations")
