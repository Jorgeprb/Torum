from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

SignalType = Literal["ENTRY", "EXIT", "MODIFY", "NONE"]
SignalSide = Literal["BUY", "SELL", "NONE"]
EntryType = Literal["MARKET"]
SignalStatus = Literal[
    "GENERATED",
    "IGNORED",
    "REJECTED_BY_RISK",
    "SENT_TO_ORDER_MANAGER",
    "ORDER_EXECUTED",
    "ORDER_FAILED",
]


class StrategySignalData(BaseModel):
    strategy_key: str
    internal_symbol: str
    timeframe: str
    side: SignalSide = "NONE"
    signal_type: SignalType = "NONE"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    entry_type: EntryType = "MARKET"
    suggested_volume: float | None = Field(default=None, gt=0)
    sl: float | None = Field(default=None, gt=0)
    tp: float | None = Field(default=None, gt=0)
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize(self) -> "StrategySignalData":
        self.strategy_key = self.strategy_key.lower()
        self.internal_symbol = self.internal_symbol.upper()
        self.timeframe = self.timeframe.upper()
        if self.signal_type == "NONE":
            self.side = "NONE"
        return self
