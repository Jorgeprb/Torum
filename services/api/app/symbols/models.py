from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SymbolMapping(Base):
    __tablename__ = "symbol_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    internal_symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    broker_symbol: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    asset_class: Mapped[str] = mapped_column(String(32), nullable=False, default="METAL")
    tradable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    analysis_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    digits: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    point: Mapped[float] = mapped_column(Float, nullable=False, default=0.01)
    contract_size: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
