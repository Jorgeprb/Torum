"""add strategy unlock notifications

Revision ID: 0017_strategy_unlocks
Revises: 0016_news_provider_finnhub
Create Date: 2026-05-08 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0017_strategy_unlocks"
down_revision: str | None = "0016_news_provider_finnhub"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_unlock_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("strategy_key", sa.String(length=100), nullable=False),
        sa.Column("internal_symbol", sa.String(length=32), nullable=False),
        sa.Column("unlock_day", sa.Date(), nullable=False),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "strategy_key",
            "internal_symbol",
            "unlock_day",
            name="uq_strategy_unlock_notifications_daily",
        ),
    )


def downgrade() -> None:
    op.drop_table("strategy_unlock_notifications")
