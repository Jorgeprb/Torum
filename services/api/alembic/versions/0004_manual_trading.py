"""manual trading

Revision ID: 0004_manual_trading
Revises: 0003_ticks_dedup_index
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_manual_trading"
down_revision: str | None = "0003_ticks_dedup_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trading_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("trading_mode", sa.String(length=16), nullable=False, server_default="PAPER"),
        sa.Column("live_trading_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_live_confirmation", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_volume", sa.Float(), nullable=False, server_default="0.01"),
        sa.Column("default_magic_number", sa.Integer(), nullable=False, server_default="260426"),
        sa.Column("default_deviation_points", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("max_order_volume", sa.Float(), nullable=True),
        sa.Column("allow_market_orders", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_pending_orders", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_trading_settings_user_id", "trading_settings", ["user_id"], unique=True)

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("internal_symbol", sa.String(length=32), nullable=False),
        sa.Column("broker_symbol", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("account_login", sa.BigInteger(), nullable=True),
        sa.Column("account_server", sa.String(length=120), nullable=True),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("requested_price", sa.Float(), nullable=True),
        sa.Column("executed_price", sa.Float(), nullable=True),
        sa.Column("sl", sa.Float(), nullable=True),
        sa.Column("tp", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("mt5_order_ticket", sa.BigInteger(), nullable=True),
        sa.Column("mt5_deal_ticket", sa.BigInteger(), nullable=True),
        sa.Column("mt5_position_ticket", sa.BigInteger(), nullable=True),
        sa.Column("magic_number", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="MANUAL"),
        sa.Column("request_payload_json", sa.JSON(), nullable=True),
        sa.Column("response_payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_orders_user_id_created_at", "orders", ["user_id", "created_at"])
    op.create_index("ix_orders_internal_symbol_created_at", "orders", ["internal_symbol", "created_at"])
    op.create_index("ix_orders_status", "orders", ["status"])

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("internal_symbol", sa.String(length=32), nullable=False),
        sa.Column("broker_symbol", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("account_login", sa.BigInteger(), nullable=True),
        sa.Column("account_server", sa.String(length=120), nullable=True),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("open_price", sa.Float(), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=True),
        sa.Column("sl", sa.Float(), nullable=True),
        sa.Column("tp", sa.Float(), nullable=True),
        sa.Column("profit", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("mt5_position_ticket", sa.BigInteger(), nullable=True),
        sa.Column("magic_number", sa.Integer(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("raw_payload_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_positions_user_id_status", "positions", ["user_id", "status"])
    op.create_index("ix_positions_internal_symbol_status", "positions", ["internal_symbol", "status"])


def downgrade() -> None:
    op.drop_index("ix_positions_internal_symbol_status", table_name="positions")
    op.drop_index("ix_positions_user_id_status", table_name="positions")
    op.drop_table("positions")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_internal_symbol_created_at", table_name="orders")
    op.drop_index("ix_orders_user_id_created_at", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_trading_settings_user_id", table_name="trading_settings")
    op.drop_table("trading_settings")
