from datetime import UTC, datetime

from app.candles.service import build_candle_rows_from_ticks, merge_candle_values, select_tick_price
from app.ticks.schemas import TickBatchRequest


def test_select_tick_price_prefers_last_when_configured() -> None:
    tick = {"bid": 100.0, "ask": 102.0, "last": 101.5}

    assert select_tick_price(tick, "BID") == 100.0
    assert select_tick_price(tick, "last_or_mid") == 101.5
    assert select_tick_price(tick, "mid") == 101.0


def test_candle_close_uses_bid_when_price_source_bid() -> None:
    ticks = [
        {
            "time": datetime(2026, 4, 26, 12, 0, 1, tzinfo=UTC),
            "internal_symbol": "XAUUSD",
            "bid": 4705.60,
            "ask": 4705.82,
            "last": None,
            "volume": 0.0,
        }
    ]

    candles = build_candle_rows_from_ticks(ticks, timeframes=("M1",), price_source="BID")

    assert candles[0]["close"] == 4705.60


def test_build_candle_ohlc_from_ticks() -> None:
    ticks = [
        {
            "time": datetime(2026, 4, 26, 12, 0, 1, tzinfo=UTC),
            "internal_symbol": "XAUUSD",
            "bid": 100.0,
            "ask": 100.0,
            "last": None,
            "volume": 1.0,
        },
        {
            "time": datetime(2026, 4, 26, 12, 0, 15, tzinfo=UTC),
            "internal_symbol": "XAUUSD",
            "bid": 102.0,
            "ask": 102.0,
            "last": None,
            "volume": 2.0,
        },
        {
            "time": datetime(2026, 4, 26, 12, 0, 55, tzinfo=UTC),
            "internal_symbol": "XAUUSD",
            "bid": 101.0,
            "ask": 101.0,
            "last": None,
            "volume": 3.0,
        },
    ]

    candles = build_candle_rows_from_ticks(ticks, timeframes=("M1",), price_source="mid")

    assert len(candles) == 1
    candle = candles[0]
    assert candle["open"] == 100.0
    assert candle["high"] == 102.0
    assert candle["low"] == 100.0
    assert candle["close"] == 101.0
    assert candle["volume"] == 6.0
    assert candle["tick_count"] == 3


def test_build_candle_creates_new_bucket() -> None:
    ticks = [
        {
            "time": datetime(2026, 4, 26, 12, 0, 1, tzinfo=UTC),
            "internal_symbol": "XAUUSD",
            "bid": 100.0,
            "ask": 100.0,
            "last": None,
            "volume": 0.0,
        },
        {
            "time": datetime(2026, 4, 26, 12, 1, 1, tzinfo=UTC),
            "internal_symbol": "XAUUSD",
            "bid": 101.0,
            "ask": 101.0,
            "last": None,
            "volume": 0.0,
        },
    ]

    candles = build_candle_rows_from_ticks(ticks, timeframes=("M1",), price_source="mid")

    assert [candle["time"] for candle in candles] == [
        datetime(2026, 4, 26, 12, 0, tzinfo=UTC),
        datetime(2026, 4, 26, 12, 1, tzinfo=UTC),
    ]


def test_merge_candle_values_updates_existing_candle() -> None:
    existing = {"open": 100.0, "high": 103.0, "low": 99.0, "close": 101.0, "volume": 2.0, "tick_count": 4}
    update = {"open": 104.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 3.0, "tick_count": 2}

    merged = merge_candle_values(existing, update)

    assert merged["open"] == 100.0
    assert merged["high"] == 105.0
    assert merged["low"] == 98.0
    assert merged["close"] == 102.0
    assert merged["volume"] == 5.0
    assert merged["tick_count"] == 6


def test_tick_batch_contract_accepts_mt5_payload() -> None:
    payload = TickBatchRequest.model_validate(
        {
            "source": "MT5",
            "ticks": [
                {
                    "internal_symbol": "XAUUSD",
                    "broker_symbol": "XAUUSD",
                    "time": "2026-04-26T12:34:56.123Z",
                    "bid": 2325.12,
                    "ask": 2325.34,
                    "last": None,
                    "volume": 0,
                }
            ],
        }
    )

    assert payload.source == "MT5"
    assert payload.ticks[0].resolved_internal_symbol == "XAUUSD"


def test_tick_batch_contract_accepts_optional_account_payload() -> None:
    payload = TickBatchRequest.model_validate(
        {
            "source": "MT5",
            "account": {
                "login": 123456,
                "server": "Broker-Demo",
                "currency": "USD",
                "company": "Broker",
                "trade_mode": "DEMO",
            },
            "ticks": [
                {
                    "internal_symbol": "XAUUSD",
                    "broker_symbol": "XAUUSD",
                    "time": "2026-04-26T12:34:56.123Z",
                    "bid": 2325.12,
                    "ask": 2325.34,
                    "last": None,
                    "volume": 0,
                }
            ],
        }
    )

    assert payload.account is not None
    assert payload.account.trade_mode == "DEMO"
