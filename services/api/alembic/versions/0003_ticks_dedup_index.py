"""deduplicate ticks

Revision ID: 0003_ticks_dedup_index
Revises: 0002_market_data_ticks_candles
Create Date: 2026-04-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_ticks_dedup_index"
down_revision: str | None = "0002_market_data_ticks_candles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_ticks_dedup
        ON ticks (internal_symbol, broker_symbol, time, bid, ask, last)
        NULLS NOT DISTINCT
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_ticks_dedup")
