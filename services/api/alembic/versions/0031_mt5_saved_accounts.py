"""Add saved MT5 accounts for passwordless terminal switching.

Revision ID: 0031_mt5_saved_accounts
Revises: 0030_strategy_performance
"""

from alembic import op
import sqlalchemy as sa

revision = "0031_mt5_saved_accounts"
down_revision = "0030_strategy_performance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mt5_saved_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=120), nullable=False),
        sa.Column("login", sa.BigInteger(), nullable=False),
        sa.Column("server", sa.String(length=160), nullable=False),
        sa.Column("last_trade_mode", sa.String(length=16), nullable=True),
        sa.Column("last_company", sa.String(length=160), nullable=True),
        sa.Column("last_currency", sa.String(length=16), nullable=True),
        sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "login", "server", name="uq_mt5_saved_accounts_user_login_server"),
    )
    op.create_index("ix_mt5_saved_accounts_user_id", "mt5_saved_accounts", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_mt5_saved_accounts_user_id", table_name="mt5_saved_accounts")
    op.drop_table("mt5_saved_accounts")
