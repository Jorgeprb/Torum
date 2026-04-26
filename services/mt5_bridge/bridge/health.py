from dataclasses import dataclass, field
from datetime import datetime

from bridge.account_state import AccountState


@dataclass(slots=True)
class BridgeHealth:
    connected_to_mt5: bool = False
    connected_to_backend: bool = False
    account_trade_mode: str = "UNKNOWN"
    account: AccountState | None = None
    active_symbols: list[str] = field(default_factory=list)
    last_tick_time_by_symbol: dict[str, datetime] = field(default_factory=dict)
    ticks_sent_total: int = 0
    last_batch_sent_at: datetime | None = None
    errors_count: int = 0
    message: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "connected_to_mt5": self.connected_to_mt5,
            "connected_to_backend": self.connected_to_backend,
            "account_trade_mode": self.account_trade_mode,
            "account": self.account.to_payload() if self.account else None,
            "active_symbols": self.active_symbols,
            "last_tick_time_by_symbol": self.last_tick_time_by_symbol,
            "ticks_sent_total": self.ticks_sent_total,
            "last_batch_sent_at": self.last_batch_sent_at,
            "errors_count": self.errors_count,
            "message": self.message,
        }
