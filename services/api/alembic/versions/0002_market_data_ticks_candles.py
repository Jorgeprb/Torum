"""market data ticks and candles

Revision ID: 0002_market_data_ticks_candles
Revises: 0001_create_users
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_market_data_ticks_candles"
down_revision: str | None = "0001_create_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "symbol_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("internal_symbol", sa.String(length=32), nullable=False),
        sa.Column("broker_symbol", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("digits", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("point", sa.Float(), nullable=False, server_default="0.01"),
        sa.Column("contract_size", sa.Float(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_symbol_mappings_internal_symbol", "symbol_mappings", ["internal_symbol"], unique=True)
    op.create_index("ix_symbol_mappings_broker_symbol", "symbol_mappings", ["broker_symbol"], unique=False)

    op.create_table(
        "ticks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("internal_symbol", sa.Text(), nullable=False),
        sa.Column("broker_symbol", sa.Text(), nullable=False),
        sa.Column("bid", sa.Float(), nullable=True),
        sa.Column("ask", sa.Float(), nullable=True),
        sa.Column("last", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", "time", name="pk_ticks"),
    )
    op.execute("SELECT create_hypertable('ticks', 'time', if_not_exists => TRUE)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ticks_time_desc ON ticks (time DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ticks_internal_symbol_time_desc ON ticks (internal_symbol, time DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ticks_broker_symbol_time_desc ON ticks (broker_symbol, time DESC)")

    op.create_table(
        "candles",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("internal_symbol", sa.Text(), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("tick_count", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("internal_symbol", "timeframe", "time", name="pk_candles"),
    )
    op.execute("SELECT create_hypertable('candles', 'time', if_not_exists => TRUE)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_candles_time_desc ON candles (time DESC)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candles_internal_symbol_timeframe_time_desc "
        "ON candles (internal_symbol, timeframe, time DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS candles")
    op.execute("DROP TABLE IF EXISTS ticks")
    op.drop_index("ix_symbol_mappings_broker_symbol", table_name="symbol_mappings")
    op.drop_index("ix_symbol_mappings_internal_symbol", table_name="symbol_mappings")
    op.drop_table("symbol_mappings")
