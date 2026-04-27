# Consistencia de precio MT5/Torum

Objetivo: la linea `BID` de Torum debe coincidir 1:1 con el `BID` del mismo simbolo en MT5.

## Flujo trazable

```text
MT5 copy_ticks_range/copy_ticks_from
  -> mt5_bridge convierte bid/ask/time_msc sin MID
  -> POST /api/ticks/batch
  -> ticks.bid y ticks.ask en TimescaleDB
  -> WebSocket latest_tick_update
  -> PWA linea BID/ASK
```

Las velas siguen construyendose en Torum. No se usan velas de MT5.

## BID, ASK, MID y CLOSE

- `BID`: precio exacto que Torum usa para la linea BID y para el close vivo si `CANDLE_PRICE_SOURCE=BID`.
- `ASK`: precio exacto que Torum usa para compras BUY.
- `MID`: `(bid + ask) / 2`. Se expone solo como diagnostico.
- `CLOSE`: cierre de vela calculado por Torum desde ticks. Con `CANDLE_PRICE_SOURCE=BID`, el close de la vela actual sigue el ultimo BID.

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

Una diferencia de varios puntos suele indicar mock activo, simbolo distinto, tick viejo, cache frontend o que se estaba mirando `MID/CLOSE` en vez de `BID`.

## Cambios aplicados

- `CANDLE_PRICE_SOURCE` queda por defecto en `BID`.
- `POST /api/ticks/batch` conserva `bid` y `ask` separados.
- Si `market_data_source=MT5`, el backend rechaza ticks `MOCK`.
- WebSocket emite `latest_tick_update` con `bid`, `ask`, `mid`, `spread`, `source` y `broker_symbol`.
- La PWA pinta lineas BID/ASK desde el ultimo tick, no desde candle close.
- Las alertas BELOW se evaluan con `bid`.

