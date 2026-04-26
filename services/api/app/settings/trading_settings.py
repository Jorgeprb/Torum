from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TradingSettings(Base):
    __tablename__ = "trading_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="PAPER")
    live_trading_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    require_live_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.01)
    default_magic_number: Mapped[int] = mapped_column(Integer, nullable=False, default=260426)
    default_deviation_points: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    max_order_volume: Mapped[float | None] = mapped_column(Float)
    allow_market_orders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_pending_orders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    long_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_take_profit_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.09)
    use_stop_loss: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lot_per_equity_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    equity_per_0_01_lot: Mapped[float] = mapped_column(Float, nullable=False, default=2500.0)
    minimum_lot: Mapped[float] = mapped_column(Float, nullable=False, default=0.01)
    allow_manual_lot_adjustment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
