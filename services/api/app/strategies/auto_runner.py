import logging

from sqlalchemy import select

from app.db.session import SessionLocal
from app.strategies.models import StrategyConfig
from app.strategies.repository import get_global_strategy_settings
from app.strategies.runner import StrategyRunner
from app.strategies.torum_v1 import TORUM_V1_KEY
from app.users.models import User

logger = logging.getLogger(__name__)


def run_torum_v1_for_symbols(symbols: list[str]) -> None:
    normalized_symbols = sorted({symbol.upper() for symbol in symbols if symbol})
    if not normalized_symbols:
        return

    with SessionLocal() as db:
        settings = get_global_strategy_settings(db)
        if not settings.strategies_enabled:
            return

        configs = list(
            db.scalars(
                select(StrategyConfig).where(
                    StrategyConfig.strategy_key == TORUM_V1_KEY,
                    StrategyConfig.enabled.is_(True),
                    StrategyConfig.internal_symbol.in_(normalized_symbols),
                )
            )
        )
        runner = StrategyRunner(db)
        for config in configs:
            if config.user_id is None:
                continue
            user = db.get(User, config.user_id)
            if user is None or not user.is_active:
                continue
            try:
                runner.run_config(config, user)
            except Exception:
                logger.exception("Torum V1 auto run failed for config %s", config.id)
