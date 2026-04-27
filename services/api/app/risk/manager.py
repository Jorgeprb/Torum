from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.mt5.schemas import MT5StatusRead
from app.news.service import get_global_news_settings
from app.no_trade_zones.service import NoTradeZoneService
from app.settings.trading_settings import TradingSettings
from app.symbols.models import SymbolMapping
from app.ticks.models import Tick
from app.trading.schemas import ManualOrderRequest
from app.risk.schemas import RiskDecision


class RiskManager:
    def __init__(self, db: Session) -> None:
        self.db = db

    def evaluate(
        self,
        order: ManualOrderRequest,
        trading_settings: TradingSettings,
        symbol_mapping: SymbolMapping | None,
        mt5_status: MT5StatusRead,
        price_stale_after_seconds: int,
    ) -> RiskDecision:
        reasons: list[str] = []
        warnings: list[str] = []
        mode = trading_settings.trading_mode
        latest_tick = self.latest_tick(order.internal_symbol)

        if trading_settings.is_paused:
            reasons.append("Trading is paused")
        if mode not in {"PAPER", "DEMO", "LIVE"}:
            reasons.append(f"Unsupported trading mode: {mode}")
        if order.order_type != "MARKET":
            reasons.append("Only market orders are allowed in Phase 4")
        if not trading_settings.allow_market_orders:
            reasons.append("Market orders are disabled")
        if getattr(trading_settings, "long_only", False) and order.side != "BUY":
            reasons.append("SELL orders are disabled because long_only is enabled")
        if not getattr(trading_settings, "use_stop_loss", True) and order.sl is not None:
            reasons.append("Stop loss is disabled by trading settings")
        if order.volume <= 0:
            reasons.append("Volume must be greater than zero")
        if trading_settings.max_order_volume is not None and order.volume > trading_settings.max_order_volume:
            reasons.append(f"Volume {order.volume} exceeds max_order_volume {trading_settings.max_order_volume}")
        if symbol_mapping is None:
            reasons.append(f"No symbol mapping found for {order.internal_symbol}")
        elif not symbol_mapping.enabled:
            reasons.append(f"Symbol mapping for {order.internal_symbol} is disabled")
        elif not symbol_mapping.broker_symbol:
            reasons.append(f"No broker_symbol configured for {order.internal_symbol}")
        elif getattr(symbol_mapping, "analysis_only", False):
            reasons.append(f"Symbol {order.internal_symbol} is analysis-only and cannot be traded.")
        elif not getattr(symbol_mapping, "tradable", True):
            reasons.append(f"Symbol {order.internal_symbol} is not tradable.")

        if latest_tick is None:
            reasons.append("No recent tick found for execution price")
        else:
            age = (datetime.now(UTC) - _as_utc(latest_tick.time)).total_seconds()
            if age > price_stale_after_seconds:
                reasons.append(f"Price is stale for {order.internal_symbol}: {int(age)}s old")
            self._validate_sl_tp(order, latest_tick, trading_settings, reasons, warnings)

        self._apply_news_zone_rules(order.internal_symbol, reasons, warnings)

        confirmation = order.client_confirmation
        if mode == "PAPER":
            return RiskDecision(allowed=not reasons, reasons=reasons, warnings=warnings)

        if not getattr(trading_settings, "mt5_order_execution_enabled", False):
            reasons.append("MT5 order execution is disabled in Torum settings")
        if not mt5_status.connected_to_mt5:
            reasons.append("MT5 bridge is disconnected")
        if mt5_status.updated_at is None:
            reasons.append("MT5 bridge status is not fresh")
        else:
            status_age = (datetime.now(UTC) - _as_utc(mt5_status.updated_at)).total_seconds()
            if status_age > max(price_stale_after_seconds * 2, 60):
                reasons.append(f"MT5 bridge status is stale: {int(status_age)}s old")

        if mode == "DEMO" and mt5_status.account_trade_mode != "DEMO":
            reasons.append(f"MT5 account mode {mt5_status.account_trade_mode} does not match configured mode DEMO")
        if mode == "LIVE":
            if mt5_status.account_trade_mode != "REAL":
                reasons.append(f"MT5 account mode {mt5_status.account_trade_mode} does not match configured mode LIVE")
            if not trading_settings.live_trading_enabled:
                reasons.append("LIVE trading is disabled")
            if trading_settings.require_live_confirmation:
                if confirmation is None or not confirmation.confirmed or confirmation.mode_acknowledged != "LIVE":
                    reasons.append("LIVE trading requires explicit confirmation")
                elif (confirmation.live_text or "").strip().upper() != "CONFIRM LIVE":
                    reasons.append("LIVE trading requires typing CONFIRM LIVE")
        elif mode == "DEMO":
            if confirmation is not None and confirmation.mode_acknowledged not in (None, "DEMO"):
                reasons.append("Client confirmation mode does not match DEMO")

        return RiskDecision(allowed=not reasons, reasons=reasons, warnings=warnings)

    def evaluate_strategy_order(
        self,
        order: ManualOrderRequest,
        trading_settings: TradingSettings,
        strategy_settings: object | None,
        symbol_mapping: SymbolMapping | None,
        mt5_status: MT5StatusRead,
        price_stale_after_seconds: int,
    ) -> RiskDecision:
        decision = self.evaluate(
            order=order,
            trading_settings=trading_settings,
            symbol_mapping=symbol_mapping,
            mt5_status=mt5_status,
            price_stale_after_seconds=price_stale_after_seconds,
        )
        reasons = list(decision.reasons)
        warnings = list(decision.warnings)
        if strategy_settings is None:
            reasons.append("Strategy settings are not configured")
        else:
            if not getattr(strategy_settings, "strategies_enabled", False):
                reasons.append("Strategies are disabled")
            if trading_settings.trading_mode == "LIVE" and not getattr(strategy_settings, "strategy_live_enabled", False):
                reasons.append("Strategy LIVE execution is disabled")
        return RiskDecision(allowed=not reasons, reasons=reasons, warnings=warnings)

    def latest_tick(self, internal_symbol: str) -> Tick | None:
        return self.db.scalar(
            select(Tick)
            .where(Tick.internal_symbol == internal_symbol)
            .order_by(Tick.time.desc(), Tick.id.desc())
            .limit(1)
        )

    def _validate_sl_tp(
        self,
        order: ManualOrderRequest,
        tick: Tick,
        trading_settings: TradingSettings,
        reasons: list[str],
        warnings: list[str],
    ) -> None:
        bid = tick.bid or tick.last
        ask = tick.ask or tick.last
        if bid is None and ask is None:
            reasons.append("Latest tick has no executable price")
            return
        price = ask if order.side == "BUY" else bid
        if price is None:
            price = bid or ask
        if price is None:
            reasons.append("Latest tick has no side price")
            return

        if order.side == "BUY":
            if order.sl is not None and order.sl >= price:
                reasons.append("BUY stop loss must be below current price")
            if order.tp is not None and order.tp <= price:
                reasons.append("BUY take profit must be above current price")
        if order.side == "SELL":
            if order.sl is not None and order.sl <= price:
                reasons.append("SELL stop loss must be above current price")
            if order.tp is not None and order.tp >= price:
                reasons.append("SELL take profit must be below current price")
        if order.sl is None and getattr(trading_settings, "use_stop_loss", True):
            warnings.append("Order has no stop loss")
        if order.sl is None and not getattr(trading_settings, "use_stop_loss", True):
            warnings.append("Order has no stop loss by configuration")
        if order.tp is None:
            warnings.append("Order has no take profit")

    def _apply_news_zone_rules(self, internal_symbol: str, reasons: list[str], warnings: list[str]) -> None:
        news_settings = get_global_news_settings(self.db)
        active_zones = NoTradeZoneService(self.db).get_active_zones(internal_symbol, datetime.now(UTC))
        if not active_zones:
            return

        blocking_zones = [zone for zone in active_zones if zone.blocks_trading]
        if news_settings.block_trading_during_news and blocking_zones:
            for zone in blocking_zones:
                reasons.append(f"Trading blocked by high-impact news zone: {zone.reason}")
            return

        if news_settings.draw_news_zones_enabled and not news_settings.block_trading_during_news:
            warnings.append("High-impact news zone active, but trading block is disabled")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
