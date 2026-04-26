from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.candles.models import Candle  # noqa: F401
from app.db.base import Base
from app.indicators.models import Indicator, IndicatorConfig, IndicatorValue  # noqa: F401
from app.drawings.models import ChartDrawing  # noqa: F401
from app.strategies.models import StrategyConfig, StrategyDefinition, StrategyRun, StrategySettings, StrategySignal  # noqa: F401
from app.news.models import NewsEvent, NewsSettings  # noqa: F401
from app.no_trade_zones.models import NoTradeZone  # noqa: F401
from app.orders.models import Order  # noqa: F401
from app.positions.models import Position  # noqa: F401
from app.settings.trading_settings import TradingSettings  # noqa: F401
from app.symbols.models import SymbolMapping  # noqa: F401
from app.ticks.models import Tick  # noqa: F401
from app.users.models import User  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
