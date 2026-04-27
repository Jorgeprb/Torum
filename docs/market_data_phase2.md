# Market Data Fase 2

## Regla principal

MT5 mandara ticks, no velas.

Torum guarda los ticks crudos en TimescaleDB y construye todas las velas OHLCV dentro del backend. La tabla `candles` se rellena exclusivamente desde ticks.

## Flujo

```text
mt5_bridge
  -> POST /api/ticks/batch
Backend
  -> valida simbolos
  -> guarda ticks
  -> agrega velas M1/M5/H1/H2/H4/D1/W1
  -> emite candle_update por WebSocket
PWA
  -> GET /api/candles para historico
  -> ws://host/ws/market/{symbol}/{timeframe} para vivo
```

## Contrato Fase 3 para mt5_bridge

Endpoint:

```text
POST /api/ticks/batch
```

Payload:

```json
{
  "source": "MT5",
  "ticks": [
    {
      "internal_symbol": "XAUUSD",
      "broker_symbol": "XAUUSD",
      "time": "2026-04-26T12:34:56.123Z",
      "bid": 2325.12,
      "ask": 2325.34,
      "last": null,
      "volume": 0
    }
  ]
}
```

El backend:

- valida que `internal_symbol` exista y este habilitado;
- normaliza `time` a UTC;
- inserta ticks en batch;
- actualiza solo las velas afectadas;
- emite `candle_update` a los clientes suscritos.
- acepta `account` opcional para registrar estado de la conexion MT5.

## Estado MT5

Fase 3 agrega:

```text
POST /api/mt5/status
GET  /api/mt5/status
```

El bridge publica:

- conexion MT5/backend;
- modo de cuenta `DEMO`, `REAL` o `UNKNOWN`;
- simbolos activos;
- ultimo tick por simbolo;
- total de ticks enviados;
- errores acumulados.

## Mock market data

Fase 2 incluye un generador mock backend. Genera ticks para:

- `XAUUSD`
- `XAUEUR`
- `XAUAUD`
- `XAUJPY`

Los ticks mock usan exactamente el mismo camino que usara MT5:

```text
mock tick -> ticks -> CandleAggregator -> candles -> WebSocket
```

Endpoints:

```text
POST /api/mock-market/start
POST /api/mock-market/stop
GET  /api/mock-market/status
```

## WebSocket

URL:

```text
ws://localhost:8000/ws/market/XAUUSD/M1
```

Mensaje de vela:

```json
{
  "type": "candle_update",
  "symbol": "XAUUSD",
  "timeframe": "M1",
  "candle": {
    "time": 1777209600,
    "internal_symbol": "XAUUSD",
    "timeframe": "M1",
    "open": 2325.1,
    "high": 2325.5,
    "low": 2324.9,
    "close": 2325.3,
    "volume": 0,
    "tick_count": 17,
    "source": "TICK_AGGREGATOR"
  }
}
```

## Consultas utiles

Ticks guardados:

```sql
select internal_symbol, broker_symbol, source, count(*), max(time)
from ticks
group by internal_symbol, broker_symbol, source
order by internal_symbol;
```

Velas generadas desde ticks:

```sql
select internal_symbol, timeframe, count(*), max(time)
from candles
group by internal_symbol, timeframe
order by internal_symbol, timeframe;
```
