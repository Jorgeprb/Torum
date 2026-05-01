from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NewsEvent(Base):
    __tablename__ = "news_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(160))
    country: Mapped[str] = mapped_column(String(80), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    impact: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_value: Mapped[str | None] = mapped_column(String(120))
    forecast_value: Mapped[str | None] = mapped_column(String(120))
    actual_value: Mapped[str | None] = mapped_column(String(120))
    url: Mapped[str | None] = mapped_column(Text)
    raw_payload_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class NewsSettings(Base):
    __tablename__ = "news_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    draw_news_zones_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    block_trading_during_news: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    minutes_before: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    minutes_after: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    currencies_filter: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    countries_filter: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    impact_filter: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    affected_symbols: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    provider_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_name: Mapped[str] = mapped_column(String(80), nullable=False, default="manual_csv_json")
    provider: Mapped[str] = mapped_column(String(24), nullable=False, default="MANUAL")
    auto_sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=360)
    days_ahead: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(24))
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
