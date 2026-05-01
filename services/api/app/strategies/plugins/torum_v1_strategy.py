from typing import Any

from app.strategies.context import StrategyContext
from app.strategies.signals import StrategySignalData
from app.strategies.torum_v1 import TORUM_V1_KEY


class TorumV1Strategy:
    key = TORUM_V1_KEY
    name = "Estrategia Torum V1.0"
    version = "1.0"
    description = "Bloqueo visual y operativo del BOT por activo usando velas cerradas y ventanas de noticias."
    default_params: dict[str, Any] = {
        "use_news": True,
        "enabled": True,
        "timeframe": "H2",
        "session_start": "09:00",
        "session_end": "15:00",
    }
    supported_symbols = ("XAUEUR", "XAUUSD")
    supported_timeframes = ("H2", "H3")
    required_indicators: tuple[str, ...] = ()
    required_context = ("candles", "no_trade_zones")

    def generate_signal(self, context: StrategyContext) -> StrategySignalData:
        return StrategySignalData(
            strategy_key=self.key,
            internal_symbol=context.symbol,
            timeframe=context.timeframe,
            signal_type="NONE",
            side="NONE",
            reason="Torum V1 es filtro de BOT. No crea orden directa.",
            metadata={"params": context.params},
        )
