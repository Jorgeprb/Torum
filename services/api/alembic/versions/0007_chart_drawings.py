"""persistent chart drawings

Revision ID: 0007_chart_drawings
Revises: 0006_indicators_dxy
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_chart_drawings"
down_revision: str | None = "0006_indicators_dxy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chart_drawings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("internal_symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("drawing_type", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("style_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="MANUAL"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chart_drawings_user_symbol_timeframe",
        "chart_drawings",
        ["user_id", "internal_symbol", "timeframe"],
    )
    op.create_index(
        "ix_chart_drawings_symbol_timeframe",
        "chart_drawings",
        ["internal_symbol", "timeframe"],
    )
    op.create_index("ix_chart_drawings_type", "chart_drawings", ["drawing_type"])
    op.create_index("ix_chart_drawings_visible", "chart_drawings", ["visible"])
    op.create_index("ix_chart_drawings_source", "chart_drawings", ["source"])


def downgrade() -> None:
    op.drop_index("ix_chart_drawings_source", table_name="chart_drawings")
    op.drop_index("ix_chart_drawings_visible", table_name="chart_drawings")
    op.drop_index("ix_chart_drawings_type", table_name="chart_drawings")
    op.drop_index("ix_chart_drawings_symbol_timeframe", table_name="chart_drawings")
    op.drop_index("ix_chart_drawings_user_symbol_timeframe", table_name="chart_drawings")
    op.drop_table("chart_drawings")
