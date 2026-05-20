"""dollar strength snapshots

Revision ID: 0019_dollar_strength_snapshots
Revises: 0018_symbol_ath_levels
Create Date: 2026-05-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_dollar_strength_snapshots"
down_revision = "0018_symbol_ath_levels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dollar_strength_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("dxy_value", sa.Float(), nullable=True),
        sa.Column("sma30", sa.Float(), nullable=True),
        sa.Column("difference", sa.Float(), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("trading_allowed", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=128), nullable=False),
        sa.Column("slope_days", sa.Integer(), nullable=False),
        sa.Column("slope_pct", sa.Float(), nullable=True),
        sa.Column("strong_drop_override_active", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("missing_symbols", sa.JSON(), nullable=False),
        sa.Column("symbols_used", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dollar_strength_snapshots_id"), "dollar_strength_snapshots", ["id"], unique=False)
    op.create_index(op.f("ix_dollar_strength_snapshots_symbol"), "dollar_strength_snapshots", ["symbol"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_dollar_strength_snapshots_symbol"), table_name="dollar_strength_snapshots")
    op.drop_index(op.f("ix_dollar_strength_snapshots_id"), table_name="dollar_strength_snapshots")
    op.drop_table("dollar_strength_snapshots")
