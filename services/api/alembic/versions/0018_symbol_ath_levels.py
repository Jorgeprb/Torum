"""symbol ath levels

Revision ID: 0018_symbol_ath_levels
Revises: 0017_strategy_unlocks
Create Date: 2026-05-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_symbol_ath_levels"
down_revision = "0017_strategy_unlocks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "symbol_ath_levels",
        sa.Column("internal_symbol", sa.String(length=32), nullable=False),
        sa.Column("ath_price", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="candles"),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("internal_symbol"),
    )


def downgrade() -> None:
    op.drop_table("symbol_ath_levels")
