"""Add strategy performance capital movement ledger.

Revision ID: 0030_strategy_performance
Revises: 0029_unify_torum_rectangles
"""

from alembic import op
import sqlalchemy as sa

revision = "0030_strategy_performance"
down_revision = "0029_unify_torum_rectangles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_capital_movements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("account_login", sa.BigInteger(), nullable=True),
        sa.Column("account_server", sa.String(length=120), nullable=True),
        sa.Column("currency", sa.String(length=12), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_login", "account_server", "external_id", name="uq_strategy_capital_mt5_event"),
    )
    op.create_index(
        "ix_strategy_capital_user_time",
        "strategy_capital_movements",
        ["user_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_strategy_capital_account_time",
        "strategy_capital_movements",
        ["account_login", "account_server", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_capital_account_time", table_name="strategy_capital_movements")
    op.drop_index("ix_strategy_capital_user_time", table_name="strategy_capital_movements")
    op.drop_table("strategy_capital_movements")
