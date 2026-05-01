"""add news provider sync settings

Revision ID: 0015_news_provider_settings
Revises: 0014_position_close_deals
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_news_provider_settings"
down_revision: str | None = "0014_position_close_deals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("news_settings", sa.Column("provider", sa.String(length=24), nullable=False, server_default="FINNHUB"))
    op.add_column("news_settings", sa.Column("auto_sync_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("news_settings", sa.Column("sync_interval_minutes", sa.Integer(), nullable=False, server_default="1440"))
    op.add_column("news_settings", sa.Column("days_ahead", sa.Integer(), nullable=False, server_default="14"))
    op.add_column("news_settings", sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("news_settings", sa.Column("last_sync_status", sa.String(length=24), nullable=True))
    op.add_column("news_settings", sa.Column("last_sync_error", sa.Text(), nullable=True))
    op.execute("UPDATE news_settings SET provider = 'FINNHUB', provider_name = 'FINNHUB', provider_enabled = true")


def downgrade() -> None:
    op.drop_column("news_settings", "last_sync_error")
    op.drop_column("news_settings", "last_sync_status")
    op.drop_column("news_settings", "last_sync_at")
    op.drop_column("news_settings", "days_ahead")
    op.drop_column("news_settings", "sync_interval_minutes")
    op.drop_column("news_settings", "auto_sync_enabled")
    op.drop_column("news_settings", "provider")
