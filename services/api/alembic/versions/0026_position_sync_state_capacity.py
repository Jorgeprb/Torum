"""Expand position sync-state capacity.

Revision ID: 0026_position_sync_capacity
Revises: 0025_torum_entry_hot_path
"""

from alembic import op
import sqlalchemy as sa

revision = "0026_position_sync_capacity"
down_revision = "0025_torum_entry_hot_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "positions",
        "sync_state",
        existing_type=sa.String(length=24),
        type_=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Current application values are deliberately <= 24 characters, so the
    # downgrade remains safe after the code update.
    op.alter_column(
        "positions",
        "sync_state",
        existing_type=sa.String(length=32),
        type_=sa.String(length=24),
        existing_nullable=False,
    )
