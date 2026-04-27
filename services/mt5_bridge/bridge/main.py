import argparse
import logging
import signal

from bridge.backend_client import BackendClient
from bridge.config import get_settings
from bridge.logging_config import configure_logging
from bridge.mt5_client import MT5Client
from bridge.order_server import start_order_server
from bridge.position_syncer import PositionSyncer
from bridge.tick_buffer import TickBuffer
from bridge.tick_collector import TickCollector

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Torum MT5 tick bridge")
    parser.add_argument("--once", action="store_true", help="Recover recent ticks, flush once and exit")
    parser.add_argument("--symbols", help="Comma-separated internal symbols override, e.g. XAUUSD,XAUEUR")
    parser.add_argument("--log-level", help="Override LOG_LEVEL")
    parser.add_argument("--market-data-only", action="store_true", help="Force market-data-only mode")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()

    if args.symbols:
        settings.mt5_symbols = args.symbols
    if args.market_data_only:
        settings.mt5_market_data_only = True

    configure_logging(args.log_level or settings.log_level)
    backend_client = BackendClient(settings)
    mt5_client = MT5Client(settings)
    tick_buffer = TickBuffer(
        backend_client=backend_client,
        batch_max_size=settings.mt5_batch_max_size,
        flush_interval_seconds=settings.mt5_batch_flush_interval_ms / 1000,
        max_buffer_size=settings.mt5_buffer_max_size,
    )
    collector = TickCollector(
        settings=settings,
        mt5_client=mt5_client,
        backend_client=backend_client,
        tick_buffer=tick_buffer,
    )
    if not args.once:
        start_order_server(settings, mt5_client)
        PositionSyncer(settings=settings, mt5_client=mt5_client, backend_client=backend_client).start()

    def stop_bridge(_signum: int, _frame: object) -> None:
        logger.info("Stop requested")
        collector.request_stop()

    signal.signal(signal.SIGINT, stop_bridge)
    signal.signal(signal.SIGTERM, stop_bridge)

    collector.run(once=args.once)


if __name__ == "__main__":
    main()
