from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    internal_symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    broker_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    account_login: Mapped[int | None] = mapped_column(BigInteger)
    account_server: Mapped[str | None] = mapped_column(String(120))
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    requested_price: Mapped[float | None] = mapped_column(Float)
    executed_price: Mapped[float | None] = mapped_column(Float)
    sl: Mapped[float | None] = mapped_column(Float)
    tp: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    mt5_order_ticket: Mapped[int | None] = mapped_column(BigInteger)
    mt5_deal_ticket: Mapped[int | None] = mapped_column(BigInteger)
    mt5_position_ticket: Mapped[int | None] = mapped_column(BigInteger)
    magic_number: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="MANUAL")
    strategy_signal_id: Mapped[int | None] = mapped_column(Integer)
    strategy_key: Mapped[str | None] = mapped_column(String(100))
    request_payload_json: Mapped[dict | None] = mapped_column(JSON)
    response_payload_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
