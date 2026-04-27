"""persist mt5 position close deal details

Revision ID: 0014_position_close_deals
Revises: 0013_tick_time_msc
Create Date: 2026-04-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_position_close_deals"
down_revision: str | None = "0013_tick_time_msc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("positions", sa.Column("close_price", sa.Float(), nullable=True))
    op.add_column("positions", sa.Column("swap", sa.Float(), nullable=True))
    op.add_column("positions", sa.Column("commission", sa.Float(), nullable=True))
    op.add_column("positions", sa.Column("closing_deal_ticket", sa.BigInteger(), nullable=True))
    op.add_column("positions", sa.Column("close_payload_json", sa.JSON(), nullable=True))
    op.execute("CREATE INDEX IF NOT EXISTS ix_positions_closing_deal_ticket ON positions (closing_deal_ticket)")
    op.execute("UPDATE positions SET close_price = current_price WHERE status = 'CLOSED' AND close_price IS NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_positions_closing_deal_ticket")
    op.drop_column("positions", "close_payload_json")
    op.drop_column("positions", "closing_deal_ticket")
    op.drop_column("positions", "commission")
    op.drop_column("positions", "swap")
    op.drop_column("positions", "close_price")
