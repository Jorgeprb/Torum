"""market price diagnostics

Revision ID: 0012_market_price_diagnostics
Revises: 0011_market_ui_trade_settings
Create Date: 2026-04-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_market_price_diagnostics"
down_revision: str | None = "0011_market_ui_trade_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trading_settings",
        sa.Column("market_data_source", sa.String(length=16), nullable=False, server_default="MT5"),
    )


def downgrade() -> None:
    op.drop_column("trading_settings", "market_data_source")
