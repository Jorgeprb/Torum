"""strategy engine base

Revision ID: 0008_strategy_engine
Revises: 0007_chart_drawings
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_strategy_engine"
down_revision: str | None = "0007_chart_drawings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("strategy_signal_id", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("strategy_key", sa.String(length=100), nullable=True))

    op.create_table(
        "strategy_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_params_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_strategy_definitions_key", "strategy_definitions", ["key"], unique=True)

    op.create_table(
        "strategy_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("strategy_key", sa.String(length=100), nullable=False),
        sa.Column("internal_symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="PAPER"),
        sa.Column("params_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("risk_profile_json", sa.JSON(), nullable=True),
        sa.Column("schedule_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_strategy_configs_symbol_timeframe", "strategy_configs", ["internal_symbol", "timeframe", "enabled"])

    op.create_table(
        "strategy_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True, unique=True),
        sa.Column("strategies_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("strategy_live_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_mode", sa.String(length=16), nullable=False, server_default="PAPER"),
        sa.Column("max_signals_per_run", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "strategy_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_config_id", sa.Integer(), sa.ForeignKey("strategy_configs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("strategy_key", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("internal_symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("signal_type", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("entry_type", sa.String(length=16), nullable=False, server_default="MARKET"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("suggested_volume", sa.Float(), nullable=True),
        sa.Column("sl", sa.Float(), nullable=True),
        sa.Column("tp", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="GENERATED"),
        sa.Column("risk_result_json", sa.JSON(), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_strategy_signals_created", "strategy_signals", ["created_at"])
    op.create_index("ix_strategy_signals_key_symbol", "strategy_signals", ["strategy_key", "internal_symbol"])

    op.create_table(
        "strategy_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_config_id", sa.Integer(), sa.ForeignKey("strategy_configs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("strategy_key", sa.String(length=100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="STARTED"),
        sa.Column("candles_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indicators_used_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("context_summary_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_strategy_runs_started", "strategy_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_strategy_runs_started", table_name="strategy_runs")
    op.drop_table("strategy_runs")
    op.drop_index("ix_strategy_signals_key_symbol", table_name="strategy_signals")
    op.drop_index("ix_strategy_signals_created", table_name="strategy_signals")
    op.drop_table("strategy_signals")
    op.drop_table("strategy_settings")
    op.drop_index("ix_strategy_configs_symbol_timeframe", table_name="strategy_configs")
    op.drop_table("strategy_configs")
    op.drop_index("ix_strategy_definitions_key", table_name="strategy_definitions")
    op.drop_table("strategy_definitions")
    op.drop_column("orders", "strategy_key")
    op.drop_column("orders", "strategy_signal_id")
