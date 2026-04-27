from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.settings.trading_settings import TradingSettings
from app.trading.schemas import TradingSettingsUpdate


def get_global_trading_settings(db: Session) -> TradingSettings:
    settings = db.scalar(select(TradingSettings).where(TradingSettings.user_id.is_(None)))
    if settings is not None:
        return settings

    app_settings = get_settings()
    settings = TradingSettings(
        user_id=None,
        trading_mode=app_settings.trading_mode,
        live_trading_enabled=app_settings.live_trading_enabled,
        require_live_confirmation=True,
        default_volume=0.01,
        default_magic_number=app_settings.default_magic_number,
        default_deviation_points=app_settings.default_deviation_points,
        max_order_volume=None,
        allow_market_orders=True,
        allow_pending_orders=False,
        is_paused=False,
        long_only=True,
        default_take_profit_percent=0.09,
        use_stop_loss=False,
        lot_per_equity_enabled=True,
        equity_per_0_01_lot=2500.0,
        minimum_lot=0.01,
        allow_manual_lot_adjustment=True,
        show_bid_line=True,
        show_ask_line=True,
        mt5_order_execution_enabled=False,
        market_data_source="MT5",
    )
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def update_global_trading_settings(db: Session, payload: TradingSettingsUpdate) -> TradingSettings:
    settings = get_global_trading_settings(db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)
    db.commit()
    db.refresh(settings)
    return settings


def seed_global_trading_settings() -> None:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        get_global_trading_settings(db)
