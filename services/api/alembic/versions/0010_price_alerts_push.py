"""price alerts and pwa push

Revision ID: 0010_price_alerts_push
Revises: 0009_mobile_buy_settings
Create Date: 2026-04-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_price_alerts_push"
down_revision: str | None = "0009_mobile_buy_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("internal_symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=True),
        sa.Column("condition_type", sa.String(length=16), nullable=False, server_default="BELOW"),
        sa.Column("target_price", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="ACTIVE"),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="CHART"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_price", sa.Float(), nullable=True),
        sa.Column("last_checked_price", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_price_alerts_user_symbol_status", "price_alerts", ["user_id", "internal_symbol", "status"])
    op.create_index("ix_price_alerts_symbol_status", "price_alerts", ["internal_symbol", "status"])
    op.create_index("ix_price_alerts_target_price", "price_alerts", ["target_price"])
    op.create_index("ix_price_alerts_created_at", "price_alerts", ["created_at"])

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("device_name", sa.String(length=120), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "endpoint", name="uq_push_subscriptions_user_endpoint"),
    )
    op.create_index("ix_push_subscriptions_user_enabled", "push_subscriptions", ["user_id", "enabled"])


def downgrade() -> None:
    op.drop_index("ix_push_subscriptions_user_enabled", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
    op.drop_index("ix_price_alerts_created_at", table_name="price_alerts")
    op.drop_index("ix_price_alerts_target_price", table_name="price_alerts")
    op.drop_index("ix_price_alerts_symbol_status", table_name="price_alerts")
    op.drop_index("ix_price_alerts_user_symbol_status", table_name="price_alerts")
    op.drop_table("price_alerts")
