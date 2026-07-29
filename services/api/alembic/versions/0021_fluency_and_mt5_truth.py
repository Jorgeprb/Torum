"""fluency and MT5 source-of-truth fields

Revision ID: 0021_fluency_and_mt5_truth
Revises: 0020_reliability_hardening
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_fluency_and_mt5_truth"
down_revision: str | None = "0020_reliability_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: Sequence[str | sa.sql.elements.TextClause],
) -> None:
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    if any(index.get("name") == index_name for index in indexes):
        return
    op.create_index(index_name, table_name, list(columns))


def upgrade() -> None:
    op.add_column("positions", sa.Column("open_time_msc", sa.BigInteger(), nullable=True))
    op.add_column("positions", sa.Column("close_time_msc", sa.BigInteger(), nullable=True))
    op.add_column(
        "positions",
        sa.Column("enrichment_status", sa.String(length=32), nullable=False, server_default="CONFIRMED"),
    )
    _create_index_if_missing(
        "ix_positions_account_server_ticket_status",
        "positions",
        ["account_login", "account_server", "mt5_position_ticket", "status"],
    )
    _create_index_if_missing(
        "ix_positions_symbol_status_opened",
        "positions",
        ["internal_symbol", "status", "opened_at"],
    )

    op.add_column("chart_drawings", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    _create_index_if_missing(
        "ix_chart_drawings_user_symbol_timeframe",
        "chart_drawings",
        ["user_id", "internal_symbol", "timeframe", "deleted_at"],
    )

    _create_index_if_missing(
        "ix_candles_symbol_timeframe_time_desc",
        "candles",
        ["internal_symbol", "timeframe", sa.text("time DESC")],
    )
    _create_index_if_missing("ix_orders_mt5_position_ticket", "orders", ["mt5_position_ticket"])


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_orders_mt5_position_ticket")
    op.execute("DROP INDEX IF EXISTS ix_candles_symbol_timeframe_time_desc")
    op.execute("DROP INDEX IF EXISTS ix_chart_drawings_user_symbol_timeframe")
    op.drop_column("chart_drawings", "revision")
    op.execute("DROP INDEX IF EXISTS ix_positions_symbol_status_opened")
    op.execute("DROP INDEX IF EXISTS ix_positions_account_server_ticket_status")
    op.drop_column("positions", "enrichment_status")
    op.drop_column("positions", "close_time_msc")
    op.drop_column("positions", "open_time_msc")
