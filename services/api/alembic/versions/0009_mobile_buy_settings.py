"""mobile buy settings

Revision ID: 0009_mobile_buy_settings
Revises: 0008_strategy_engine
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_mobile_buy_settings"
down_revision: str | None = "0008_strategy_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trading_settings", sa.Column("long_only", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column(
        "trading_settings",
        sa.Column("default_take_profit_percent", sa.Float(), nullable=False, server_default="0.09"),
    )
    op.add_column("trading_settings", sa.Column("use_stop_loss", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("trading_settings", sa.Column("lot_per_equity_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column(
        "trading_settings",
        sa.Column("equity_per_0_01_lot", sa.Float(), nullable=False, server_default="2500"),
    )
    op.add_column("trading_settings", sa.Column("minimum_lot", sa.Float(), nullable=False, server_default="0.01"))
    op.add_column(
        "trading_settings",
        sa.Column("allow_manual_lot_adjustment", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("trading_settings", "allow_manual_lot_adjustment")
    op.drop_column("trading_settings", "minimum_lot")
    op.drop_column("trading_settings", "equity_per_0_01_lot")
    op.drop_column("trading_settings", "lot_per_equity_enabled")
    op.drop_column("trading_settings", "use_stop_loss")
    op.drop_column("trading_settings", "default_take_profit_percent")
    op.drop_column("trading_settings", "long_only")
