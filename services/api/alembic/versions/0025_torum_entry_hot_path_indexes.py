"""harden and index the Torum entry hot path

Revision ID: 0025_torum_entry_hot_path
Revises: 0024_torum_reservation_indexes
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025_torum_entry_hot_path"
down_revision: str | None = "0024_torum_reservation_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Replace the first reservation indexes with account/mode-aware versions
    # and include the ambiguous-response reconciliation status.
    op.execute("DROP INDEX IF EXISTS ix_orders_torum_active_reservations")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_orders_torum_active_reservations
        ON orders (user_id, internal_symbol, mode, account_login, account_server, created_at DESC)
        WHERE source = 'STRATEGY'
          AND strategy_key = 'torum_v1'
          AND status IN ('CREATED', 'VALIDATING', 'SENT', 'RECONCILING')
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_strategy_signals_torum_active_reservations")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_strategy_signals_torum_active_reservations
        ON strategy_signals (user_id, internal_symbol, strategy_config_id, created_at DESC)
        WHERE strategy_key = 'torum_v1'
          AND signal_type = 'ENTRY'
          AND side = 'BUY'
          AND status IN ('RISK_APPROVED', 'SENT_TO_ORDER_MANAGER', 'ORDER_RECONCILING')
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_strategy_configs_torum_latest_enabled
        ON strategy_configs (user_id, internal_symbol, revision DESC, id DESC)
        WHERE strategy_key = 'torum_v1' AND enabled = true
        """
    )
    # Old databases may contain a seeded PAPER row and a later DEMO/LIVE row
    # enabled for the same asset. Keep only the newest revision before adding
    # the invariant that prevents this from recurring.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY COALESCE(user_id, 0), LOWER(strategy_key), UPPER(internal_symbol)
                    ORDER BY revision DESC, id DESC
                ) AS row_number
            FROM strategy_configs
            WHERE strategy_key = 'torum_v1' AND enabled = true
        )
        UPDATE strategy_configs AS config
        SET enabled = false, updated_at = NOW()
        FROM ranked
        WHERE config.id = ranked.id AND ranked.row_number > 1
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_configs_one_enabled_torum_asset
        ON strategy_configs (
            COALESCE(user_id, 0),
            LOWER(strategy_key),
            UPPER(internal_symbol)
        )
        WHERE strategy_key = 'torum_v1' AND enabled = true
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_strategy_signals_torum_setup_lookup
        ON strategy_signals (user_id, internal_symbol, id DESC)
        WHERE strategy_key = 'torum_v1'
          AND signal_type = 'ENTRY'
          AND side = 'BUY'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_positions_torum_open_by_user_symbol
        ON positions (user_id, internal_symbol, mode, account_login, account_server, order_id)
        WHERE status = 'OPEN' AND closed_at IS NULL AND close_price IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chart_drawings_torum_active
        ON chart_drawings (user_id, internal_symbol, drawing_type)
        WHERE visible = true AND source = 'MANUAL' AND deleted_at IS NULL
        """
    )

    # Seed/correct automatic ATH rows during deployment, outside the first live
    # entry. Manual ATH values are deliberately preserved.
    op.execute(
        """
        INSERT INTO symbol_ath_levels
            (internal_symbol, ath_price, source, calculated_at, updated_at)
        SELECT internal_symbol, MAX(high), 'candles', NOW(), NOW()
        FROM candles
        WHERE internal_symbol IN ('XAUUSD', 'XAUEUR')
        GROUP BY internal_symbol
        ON CONFLICT (internal_symbol) DO UPDATE
        SET ath_price = GREATEST(symbol_ath_levels.ath_price, EXCLUDED.ath_price),
            calculated_at = NOW(),
            updated_at = NOW()
        WHERE symbol_ath_levels.source <> 'manual'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_strategy_configs_one_enabled_torum_asset")
    op.execute("DROP INDEX IF EXISTS ix_chart_drawings_torum_active")
    op.execute("DROP INDEX IF EXISTS ix_positions_torum_open_by_user_symbol")
    op.execute("DROP INDEX IF EXISTS ix_strategy_signals_torum_setup_lookup")
    op.execute("DROP INDEX IF EXISTS ix_strategy_configs_torum_latest_enabled")

    # Restore the exact 0024 index definitions.
    op.execute("DROP INDEX IF EXISTS ix_strategy_signals_torum_active_reservations")
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
    op.execute("DROP INDEX IF EXISTS ix_orders_torum_active_reservations")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_orders_torum_active_reservations
        ON orders (internal_symbol, user_id, created_at)
        WHERE source = 'STRATEGY'
          AND strategy_key = 'torum_v1'
          AND status IN ('CREATED', 'VALIDATING', 'SENT')
        """
    )
