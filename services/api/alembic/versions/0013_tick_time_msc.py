"""persist tick millisecond ordering

Revision ID: 0013_tick_time_msc
Revises: 0012_market_price_diagnostics
Create Date: 2026-04-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_tick_time_msc"
down_revision: str | None = "0012_market_price_diagnostics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ticks", sa.Column("time_msc", sa.BigInteger(), nullable=True))
    op.execute("UPDATE ticks SET time_msc = (EXTRACT(EPOCH FROM time) * 1000)::bigint WHERE time_msc IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ticks_internal_symbol_time_msc_desc ON ticks (internal_symbol, time_msc DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ticks_broker_symbol_time_msc_desc ON ticks (broker_symbol, time_msc DESC)")

    op.add_column("candles", sa.Column("first_tick_time_msc", sa.BigInteger(), nullable=True))
    op.add_column("candles", sa.Column("last_tick_time_msc", sa.BigInteger(), nullable=True))
    op.execute(
        """
        UPDATE candles
        SET
            first_tick_time_msc = (EXTRACT(EPOCH FROM time) * 1000)::bigint,
            last_tick_time_msc = (EXTRACT(EPOCH FROM time) * 1000)::bigint
        WHERE first_tick_time_msc IS NULL OR last_tick_time_msc IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ticks_broker_symbol_time_msc_desc")
    op.execute("DROP INDEX IF EXISTS ix_ticks_internal_symbol_time_msc_desc")
    op.drop_column("candles", "last_tick_time_msc")
    op.drop_column("candles", "first_tick_time_msc")
    op.drop_column("ticks", "time_msc")

