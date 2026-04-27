# Consistencia de precio MT5/Torum

Objetivo: la linea `BID` de Torum debe coincidir 1:1 con el `BID` del mismo simbolo en MT5.

## Flujo trazable

```text
MT5 copy_ticks_range/copy_ticks_from
  + MT5 symbol_info_tick snapshot actual
  -> mt5_bridge convierte bid/ask/time_msc sin MID
  -> POST /api/ticks/batch
  -> ticks.bid, ticks.ask y ticks.time_msc en TimescaleDB
  -> WebSocket latest_tick_update
  -> PWA linea BID/ASK
```

Las velas siguen construyendose en Torum. No se usan velas de MT5.

## BID, ASK, MID y CLOSE

- `BID`: precio exacto que Torum usa para la linea BID y para el close vivo si `CANDLE_PRICE_SOURCE=BID`.
- `ASK`: precio exacto que Torum usa para compras BUY.
- `MID`: `(bid + ask) / 2`. Se expone solo como diagnostico.
- `CLOSE`: cierre de vela calculado por Torum desde ticks. Con `CANDLE_PRICE_SOURCE=BID`, el close de la vela actual sigue el ultimo BID.

El precio actual de la PWA no sale de `CLOSE`. Sale de `latestTick.bid`. Las velas son historico/estructura; el tick es la fuente viva de precio.

## Endpoint de ultimo tick

```powershell
Invoke-RestMethod "http://localhost:8000/api/market/latest-tick?symbol=XAUUSD"
```

Debe devolver el ultimo tick guardado, no una vela:

```json
{
  "symbol": "XAUUSD",
  "broker_symbol": "XAUUSD",
  "source": "MT5",
  "bid": 4698.59,
  "ask": 4698.80,
  "mid": 4698.695,
  "time_msc": 1777298046937,
  "age_ms": 350
}
```

## Como comprobar contra MT5

1. En MT5, mira el simbolo exacto de Market Watch: `XAUUSD`, `XAUUSD`, etc.
2. En Torum, abre Ajustes -> Diagnostico de mercado.
3. Comprueba `Broker mapping`.
4. Comprueba `source=MT5`.
5. Comprueba que `Mock=apagado`.
6. Comprueba `Backend latest BID/ASK`.
7. Comprueba `Frontend latest BID/ASK`.
8. Comprueba `Candle close (BID)`.

Una diferencia de varios puntos suele indicar mock activo, simbolo distinto, tick viejo, cache frontend, orden incorrecto sin `time_msc` o que se estaba mirando `MID/CLOSE` en vez de `BID`.

## Cambios aplicados

- `CANDLE_PRICE_SOURCE` queda por defecto en `BID`.
- `POST /api/ticks/batch` conserva `bid` y `ask` separados.
- Si `market_data_source=MT5`, el backend rechaza ticks `MOCK`.
- WebSocket emite `latest_tick_update` con `bid`, `ask`, `mid`, `spread`, `source` y `broker_symbol`.
- WebSocket y REST incluyen `time_msc`.
- `latest_tick` y `get_recent_ticks` ordenan por `time_msc DESC`, no solo por `time`.
- El bridge anade el snapshot actual de `symbol_info_tick()` a cada ciclo para que Torum pueda mostrar el mismo BID/ASK que ves en MT5 Market Watch.
- La PWA pinta lineas BID/ASK desde el ultimo tick, no desde candle close.
- Las alertas BELOW se evaluan con `bid`.

## Verificacion SQL

La vela actual debe tener close igual al ultimo BID del bucket cuando `CANDLE_PRICE_SOURCE=BID`:

```powershell
docker compose exec -T timescaledb psql -U torum -d torum -c "with b as (select time as bucket from candles where internal_symbol='XAUUSD' and timeframe='M1' order by time desc limit 1), lt as (select t.time, t.time_msc, t.bid, t.ask from ticks t, b where t.internal_symbol='XAUUSD' and t.time >= b.bucket and t.time < b.bucket + interval '1 minute' order by t.time_msc desc nulls last, t.time desc, t.id desc limit 1) select b.bucket, c.close, c.last_tick_time_msc, lt.time_msc, lt.bid, c.close = lt.bid as close_equals_bid from b join candles c on c.internal_symbol='XAUUSD' and c.timeframe='M1' and c.time=b.bucket join lt on true;"
```
