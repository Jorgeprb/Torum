"""news events and no trade zones

Revision ID: 0005_news_no_trade_zones
Revises: 0004_manual_trading
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_news_no_trade_zones"
down_revision: str | None = "0004_manual_trading"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("external_id", sa.String(length=160), nullable=True),
        sa.Column("country", sa.String(length=80), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("impact", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_value", sa.String(length=120), nullable=True),
        sa.Column("forecast_value", sa.String(length=120), nullable=True),
        sa.Column("actual_value", sa.String(length=120), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_news_events_event_time", "news_events", ["event_time"])
    op.create_index("ix_news_events_currency_impact_time", "news_events", ["currency", "impact", "event_time"])
    op.create_index("ix_news_events_source_external_id", "news_events", ["source", "external_id"], unique=True)

    op.create_table(
        "news_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("draw_news_zones_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("block_trading_during_news", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("minutes_before", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("minutes_after", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("currencies_filter", sa.JSON(), nullable=False, server_default=sa.text("'[\"USD\"]'::json")),
        sa.Column("countries_filter", sa.JSON(), nullable=False, server_default=sa.text("'[\"US\", \"United States\"]'::json")),
        sa.Column("impact_filter", sa.JSON(), nullable=False, server_default=sa.text("'[\"HIGH\"]'::json")),
        sa.Column(
            "affected_symbols",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"XAUUSD\", \"XAUEUR\", \"XAUAUD\", \"XAUJPY\"]'::json"),
        ),
        sa.Column("provider_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_name", sa.String(length=80), nullable=False, server_default="manual_csv_json"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_news_settings_user_id", "news_settings", ["user_id"], unique=True)

    op.create_table(
        "no_trade_zones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("news_event_id", sa.Integer(), sa.ForeignKey("news_events.id", ondelete="CASCADE"), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.String(length=320), nullable=False),
        sa.Column("internal_symbol", sa.String(length=32), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("blocks_trading", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("visual_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_no_trade_zones_symbol_window", "no_trade_zones", ["internal_symbol", "start_time", "end_time"])
    op.create_index("ix_no_trade_zones_enabled", "no_trade_zones", ["enabled"])
    op.create_index("ix_no_trade_zones_blocks_trading", "no_trade_zones", ["blocks_trading"])


def downgrade() -> None:
    op.drop_index("ix_no_trade_zones_blocks_trading", table_name="no_trade_zones")
    op.drop_index("ix_no_trade_zones_enabled", table_name="no_trade_zones")
    op.drop_index("ix_no_trade_zones_symbol_window", table_name="no_trade_zones")
    op.drop_table("no_trade_zones")
    op.drop_index("ix_news_settings_user_id", table_name="news_settings")
    op.drop_table("news_settings")
    op.drop_index("ix_news_events_source_external_id", table_name="news_events")
    op.drop_index("ix_news_events_currency_impact_time", table_name="news_events")
    op.drop_index("ix_news_events_event_time", table_name="news_events")
    op.drop_table("news_events")
