"""strategy workbench, configuration revisions and news rules

Revision ID: 0022_strategy_workbench
Revises: 0021_fluency_and_mt5_truth
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_strategy_workbench"
down_revision: str | None = "0021_fluency_and_mt5_truth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("strategy_configs", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "strategy_config_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_config_id", sa.Integer(), sa.ForeignKey("strategy_configs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("risk_profile_json", sa.JSON(), nullable=True),
        sa.Column("schedule_json", sa.JSON(), nullable=True),
        sa.Column("change_note", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("strategy_config_id", "revision", name="uq_strategy_config_versions_revision"),
    )
    op.create_index("ix_strategy_config_versions_strategy_config_id", "strategy_config_versions", ["strategy_config_id"])

    op.add_column("news_settings", sa.Column("impact_rules_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    op.add_column("news_settings", sa.Column("manual_trade_policy", sa.String(length=24), nullable=False, server_default="WARN"))
    op.add_column("news_settings", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("news_settings", "revision")
    op.drop_column("news_settings", "manual_trade_policy")
    op.drop_column("news_settings", "impact_rules_json")
    op.drop_index("ix_strategy_config_versions_strategy_config_id", table_name="strategy_config_versions")
    op.drop_table("strategy_config_versions")
    op.drop_column("strategy_configs", "revision")
