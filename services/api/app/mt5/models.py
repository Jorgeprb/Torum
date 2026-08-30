from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SavedMT5Account(Base):
    __tablename__ = "mt5_saved_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "login", "server", name="uq_mt5_saved_accounts_user_login_server"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(120), nullable=False)
    login: Mapped[int] = mapped_column(BigInteger, nullable=False)
    server: Mapped[str] = mapped_column(String(160), nullable=False)
    last_trade_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_company: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
