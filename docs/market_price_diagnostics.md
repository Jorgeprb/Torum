# Market price diagnostics

Torum now exposes a traceable path from MT5 tick to chart:

```text
mt5_bridge copy_ticks_range
  -> POST /api/ticks/batch
  -> ticks table
  -> CandleAggregator
  -> REST /api/candles + WebSocket latest_tick_update
  -> Lightweight Charts
```

## Price labels

- `BID`: price buyers can sell into. Torum uses this as default candle price source.
- `ASK`: price buyers pay to open BUY.
- `MID`: `(bid + ask) / 2`, useful for analysis but not used by default candles.
- `CLOSE`: latest candle close calculated by Torum from ticks. With `CANDLE_PRICE_SOURCE=BID`, the live candle close follows latest bid.

## Latest tick endpoint

```powershell
Invoke-RestMethod "http://localhost:8000/api/market/latest-tick?symbol=XAUUSD"
```

The response is the latest raw tick saved in TimescaleDB. It is not a candle close.

Fields to compare with MT5:

- `internal_symbol`
- `broker_symbol`
- `source`
- `time`
- `bid`
- `ask`
- `mid`
- `spread`
- `age_ms`

## How to compare Torum with MT5

1. In MT5, confirm the exact Market Watch symbol, for example `XAUUSD` or `XAUUSD`.
2. In Torum, open Ajustes -> Diagnostico de mercado.
3. Check `Broker mapping`; it must match the MT5 symbol you are comparing.
4. Check `Backend latest`; it must show `source=MT5`.
5. Check `Mock`; it should be `apagado` while using MT5.
6. Check `Candle close`; it should show `(BID)`.
7. Compare MT5 BID with Torum backend/latest BID, not with an unlabeled chart value.

## Common causes of a 5+ point difference

- mock market was active and old `MOCK` ticks were visible;
- MT5 chart was opened on a different broker symbol than `symbol_mappings.broker_symbol`;
- the tick was stale;
- the chart value was candle `CLOSE` or `MID` instead of latest `BID`;
- frontend state cached the previous symbol or timeframe.

## Source guard

`trading_settings.market_data_source` can be:

- `MT5`
- `MOCK`

When `market_data_source=MT5`, backend ignores incoming `MOCK` ticks for live ingestion. This prevents accidental source mixing while leaving mock available when explicitly selected.

## Bridge diagnostics

The bridge logs symbol mapping and periodic tick summaries:

```text
XAUUSD -> XAUUSD | bid=4705.60 ask=4705.82 time_msc=... sent=128 source=MT5
```

Configure interval:

```text
MT5_DIAGNOSTIC_LOG_INTERVAL_SECONDS=5
```
