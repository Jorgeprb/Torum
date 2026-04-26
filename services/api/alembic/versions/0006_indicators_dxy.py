"""indicators and dxy symbol metadata

Revision ID: 0006_indicators_dxy
Revises: 0005_news_no_trade_zones
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_indicators_dxy"
down_revision: str | None = "0005_news_no_trade_zones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("symbol_mappings", sa.Column("asset_class", sa.String(length=32), nullable=False, server_default="METAL"))
    op.add_column("symbol_mappings", sa.Column("tradable", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("symbol_mappings", sa.Column("analysis_only", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(
        """
        insert into symbol_mappings (
            internal_symbol, broker_symbol, display_name, enabled, asset_class,
            tradable, analysis_only, digits, point, contract_size
        )
        values ('DXY', 'DXY', 'US Dollar Index', true, 'INDEX', false, true, 2, 0.01, 1.0)
        on conflict (internal_symbol) do update set
            display_name = excluded.display_name,
            asset_class = excluded.asset_class,
            tradable = false,
            analysis_only = true
        """
    )

    op.create_table(
        "indicators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("plugin_key", sa.String(length=80), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("output_type", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_params_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_indicators_plugin_key", "indicators", ["plugin_key"], unique=True)

    op.create_table(
        "indicator_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("indicator_id", sa.Integer(), sa.ForeignKey("indicators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("internal_symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("params_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("display_settings_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_indicator_configs_symbol_timeframe",
        "indicator_configs",
        ["internal_symbol", "timeframe", "enabled"],
    )

    op.create_table(
        "indicator_values",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("internal_symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("indicator_key", sa.String(length=80), nullable=False),
        sa.Column("config_id", sa.Integer(), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("time", "internal_symbol", "timeframe", "indicator_key"),
    )


def downgrade() -> None:
    op.drop_table("indicator_values")
    op.drop_index("ix_indicator_configs_symbol_timeframe", table_name="indicator_configs")
    op.drop_table("indicator_configs")
    op.drop_index("ix_indicators_plugin_key", table_name="indicators")
    op.drop_table("indicators")
    op.drop_column("symbol_mappings", "analysis_only")
    op.drop_column("symbol_mappings", "tradable")
    op.drop_column("symbol_mappings", "asset_class")
