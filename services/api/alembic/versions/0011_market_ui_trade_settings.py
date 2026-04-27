"""market ui and mt5 execution settings

Revision ID: 0011_market_ui_trade_settings
Revises: 0010_price_alerts_push
Create Date: 2026-04-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_market_ui_trade_settings"
down_revision: str | None = "0010_price_alerts_push"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trading_settings", sa.Column("show_bid_line", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("trading_settings", sa.Column("show_ask_line", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column(
        "trading_settings",
        sa.Column("mt5_order_execution_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("trading_settings", "mt5_order_execution_enabled")
    op.drop_column("trading_settings", "show_ask_line")
    op.drop_column("trading_settings", "show_bid_line")
