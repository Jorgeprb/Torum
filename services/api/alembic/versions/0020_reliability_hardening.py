"""reliability hardening

Revision ID: 0020_reliability_hardening
Revises: 0019_dollar_strength_snapshots
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_reliability_hardening"
down_revision: str | None = "0019_dollar_strength_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("positions", sa.Column("fee", sa.Float(), nullable=True))
    op.add_column("positions", sa.Column("missing_sync_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("positions", sa.Column("last_seen_mt5_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("positions", sa.Column("sync_state", sa.String(length=24), nullable=False, server_default="CONFIRMED"))
    op.execute(
        """
        WITH ranked AS (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY account_login, account_server, mt5_position_ticket
                ORDER BY CASE WHEN status='OPEN' THEN 0 ELSE 1 END, id DESC
            ) AS rn
            FROM positions
            WHERE account_login IS NOT NULL
              AND account_server IS NOT NULL
              AND mt5_position_ticket IS NOT NULL
        )
        UPDATE positions
        SET mt5_position_ticket = NULL, sync_state = 'DUPLICATE_TICKET'
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_positions_account_server_ticket "
        "ON positions (account_login, account_server, mt5_position_ticket) "
        "WHERE mt5_position_ticket IS NOT NULL "
        "AND account_login IS NOT NULL AND account_server IS NOT NULL"
    )

    op.add_column("symbol_mappings", sa.Column("profit_currency", sa.String(length=8), nullable=True))
    op.add_column(
        "symbol_mappings",
        sa.Column("risk_conversion_rate", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.execute("UPDATE symbol_mappings SET profit_currency='USD' WHERE internal_symbol IN ('XAUUSD','DXY')")
    op.execute("UPDATE symbol_mappings SET profit_currency='EUR' WHERE internal_symbol='XAUEUR'")

    op.create_table(
        "trade_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_type", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rerun_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_trade_jobs_idempotency_key"),
    )
    op.create_index("ix_trade_jobs_job_type", "trade_jobs", ["job_type"])
    op.create_index("ix_trade_jobs_status", "trade_jobs", ["status"])
    op.create_index("ix_trade_jobs_status_next_run", "trade_jobs", ["status", "next_run_at"])

    op.create_table(
        "risk_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_login", sa.BigInteger(), nullable=True),
        sa.Column("account_server", sa.String(length=120), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="ALL"),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "account_login",
            "account_server",
            "symbol",
            "source",
            name="uq_risk_snapshots_account_symbol_source",
        ),
    )
    op.create_index("ix_risk_snapshots_symbol", "risk_snapshots", ["symbol"])

    op.execute("DROP INDEX IF EXISTS ux_ticks_dedup")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_ticks_dedup
        ON ticks (internal_symbol, broker_symbol, time, time_msc, bid, ask, last)
        NULLS NOT DISTINCT
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            ALTER TABLE ticks SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'internal_symbol,broker_symbol',
                timescaledb.compress_orderby = 'time DESC'
            );
            PERFORM add_compression_policy('ticks', INTERVAL '7 days', if_not_exists => TRUE);
            PERFORM add_retention_policy('ticks', INTERVAL '180 days', if_not_exists => TRUE);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Timescale tick policies were not applied: %', SQLERRM;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            ALTER TABLE candles SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'internal_symbol,timeframe',
                timescaledb.compress_orderby = 'time DESC'
            );
            PERFORM add_compression_policy('candles', INTERVAL '30 days', if_not_exists => TRUE);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Timescale candle policies were not applied: %', SQLERRM;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_ticks_dedup")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_ticks_dedup
        ON ticks (internal_symbol, broker_symbol, time, bid, ask, last)
        NULLS NOT DISTINCT
        """
    )
    op.drop_index("ix_risk_snapshots_symbol", table_name="risk_snapshots")
    op.drop_table("risk_snapshots")
    op.drop_index("ix_trade_jobs_status_next_run", table_name="trade_jobs")
    op.drop_index("ix_trade_jobs_status", table_name="trade_jobs")
    op.drop_index("ix_trade_jobs_job_type", table_name="trade_jobs")
    op.drop_table("trade_jobs")
    op.drop_column("symbol_mappings", "risk_conversion_rate")
    op.drop_column("symbol_mappings", "profit_currency")
    op.execute("DROP INDEX IF EXISTS ux_positions_account_server_ticket")
    op.drop_column("positions", "sync_state")
    op.drop_column("positions", "last_seen_mt5_at")
    op.drop_column("positions", "missing_sync_count")
    op.drop_column("positions", "fee")
