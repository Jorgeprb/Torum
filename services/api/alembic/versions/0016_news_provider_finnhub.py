"""switch news provider to finnhub

Revision ID: 0016_news_provider_finnhub
Revises: 0015_news_provider_settings
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016_news_provider_finnhub"
down_revision: str | None = "0015_news_provider_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE news_settings
        SET provider = 'FINNHUB',
            provider_name = 'FINNHUB',
            provider_enabled = true,
            auto_sync_enabled = true,
            sync_interval_minutes = 1440,
            days_ahead = CASE WHEN days_ahead < 14 THEN 14 ELSE days_ahead END
        WHERE provider != 'FINNHUB'
           OR provider_name != 'FINNHUB'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE news_settings
        SET provider = 'MANUAL',
            provider_name = 'manual_csv_json',
            provider_enabled = false,
            auto_sync_enabled = false
        WHERE provider = 'FINNHUB'
        """
    )
