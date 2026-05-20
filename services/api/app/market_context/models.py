from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DollarStrengthSnapshot(Base):
    __tablename__ = "dollar_strength_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, default="DXY", index=True)
    dxy_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    sma30: Mapped[float | None] = mapped_column(Float, nullable=True)
    difference: Mapped[float | None] = mapped_column(Float, nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN")
    trading_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason: Mapped[str] = mapped_column(String(128), nullable=False, default="usd_strength_unknown")
    slope_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    slope_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    strong_drop_override_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="synthetic_mt5")
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    missing_symbols: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    symbols_used: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
