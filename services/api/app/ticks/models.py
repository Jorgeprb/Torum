from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Identity, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Tick(Base):
    __tablename__ = "ticks"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    time_msc: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    internal_symbol: Mapped[str] = mapped_column(Text, nullable=False)
    broker_symbol: Mapped[str] = mapped_column(Text, nullable=False)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    last: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
