from __future__ import annotations

import argparse
import logging
import signal

from bridge.backend_client import BackendClient
from bridge.config import get_settings
from bridge.logging_config import configure_logging
from bridge.mt5_client import MT5Client
from bridge.order_server import OrderServerHandle, start_order_server
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

    configure_logging(
        args.log_level or settings.log_level,
        log_to_file=settings.mt5_log_to_file,
        log_directory=settings.mt5_log_directory or None,
        max_bytes=settings.mt5_log_max_bytes,
        backup_count=settings.mt5_log_backup_count,
    )
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

    order_server: OrderServerHandle | None = None
    position_syncer: PositionSyncer | None = None
    if not args.once:
        position_syncer = PositionSyncer(settings=settings, mt5_client=mt5_client, backend_client=backend_client)
        position_syncer.start()

        def switch_active_account(login: int, server: str):
            # Switching owns the highest-priority MT5 slot. Finish posting any
            # already collected old-account ticks before changing the terminal;
            # batches are also individually account-tagged as a second guard.
            with mt5_client.operation("order", f"account_switch:{login}"):
                previous = mt5_client.get_account_state()
                tick_buffer.flush(account=previous.to_payload(), force=True, timeout=5.0)
                previous, current = mt5_client.switch_account(login, server)
                position_syncer.request_sync()
                return previous, current

        order_server = start_order_server(
            settings,
            mt5_client,
            account_switch_handler=switch_active_account,
        )

    def stop_bridge(_signum: int, _frame: object) -> None:
        logger.info("Stop requested")
        collector.request_stop()

    signal.signal(signal.SIGINT, stop_bridge)
    signal.signal(signal.SIGTERM, stop_bridge)

    try:
        collector.run(once=args.once)
    finally:
        if position_syncer is not None:
            position_syncer.stop()
        if order_server is not None:
            order_server.stop()
        tick_buffer.stop(flush=True)
        mt5_client.shutdown()


if __name__ == "__main__":
    main()
