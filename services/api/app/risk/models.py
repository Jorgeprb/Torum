from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RiskSnapshotRecord(Base):
    __tablename__ = "risk_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "account_login",
            "account_server",
            "symbol",
            "source",
            name="uq_risk_snapshots_account_symbol_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_login: Mapped[int | None] = mapped_column(BigInteger)
    account_server: Mapped[str | None] = mapped_column(String(120))
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="ALL")
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dirty: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
