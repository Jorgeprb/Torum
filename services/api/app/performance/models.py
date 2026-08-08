from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CapitalMovement(Base):
    """External cash movement used to neutralize deposits/withdrawals in returns."""

    __tablename__ = "strategy_capital_movements"
    __table_args__ = (
        UniqueConstraint(
            "account_login",
            "account_server",
            "external_id",
            name="uq_strategy_capital_mt5_event",
        ),
        Index("ix_strategy_capital_user_time", "user_id", "occurred_at"),
        Index("ix_strategy_capital_account_time", "account_login", "account_server", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    account_login: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    account_server: Mapped[str | None] = mapped_column(String(120), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(12), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="MANUAL")
    external_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
