# Posiciones

Torum pinta posiciones abiertas sobre el grafico usando overlays, no dibujos persistentes.

## Lineas en grafico

Para una posicion BUY abierta:

- linea azul de entrada: `BUY volumen, resultado`;
- linea verde de TP: `TP, beneficio estimado, porcentaje`;
- marcadores `BUY` y `CLOSE` sobre las velas cuando hay orden ejecutada o cierre.

La linea TP solo es arrastrable cuando la posicion BUY esta seleccionada y el panel inferior esta abierto. Si no esta seleccionada, la linea TP se pinta mas apagada y no envia cambios. Al soltarla, la PWA llama:

```text
PATCH /api/positions/{id}/tp
```

El backend valida que la posicion este abierta, que sea BUY y que `tp > open_price`. En `PAPER` actualiza base de datos. En `DEMO/LIVE` llama al bridge, que usa:

```text
TRADE_ACTION_SLTP
```

No se crea stop loss; `sl` se mantiene en `0`.

## Cerrar posicion

Al tocar la linea de entrada BUY, se abre un panel inferior compacto. El boton de cierre pide confirmacion y llama:

```text
POST /api/positions/{id}/close
```

En `PAPER` se cierra localmente. En `DEMO/LIVE`, el backend llama al bridge:

```text
POST /positions/{ticket}/close
```

Para cerrar una BUY, el bridge envia una SELL de igual volumen al BID actual.

## Sincronizacion con MT5

El `mt5_bridge` ejecuta un polling periodico de `positions_get()` y publica:

```text
POST /api/mt5/positions/sync
```

`positions_get()` es la fuente de verdad para posiciones abiertas. El bridge tambien consulta `history_deals_get(date_from, date_to)` y filtra deals de cierre con:

```text
DEAL_ENTRY_OUT
DEAL_ENTRY_INOUT
DEAL_ENTRY_OUT_BY
```

El backend hace upsert por `mt5_position_ticket`. Si un ticket que estaba abierto desaparece del listado de MT5 para la misma cuenta, Torum busca un deal de cierre por `deal.position_id == mt5_position_ticket` y marca la posicion como `CLOSED`.

Cuando encuentra el deal de cierre guarda:

- `closed_at`
- `close_price`
- `profit`
- `swap`
- `commission`
- `closing_deal_ticket`
- `close_payload_json`

Si una posicion local no tenia `account_login` o `account_server` guardado, la reconciliacion tambien la puede cerrar cuando el bridge sincroniza la cuenta actual. Esto evita posiciones fantasma que seguian `OPEN` despues de cerrar en MT5.

Cuando MT5 sincroniza cambios, el backend emite un evento WebSocket de posicion y la PWA recarga posiciones/historial. Si el usuario tenia seleccionado un BUY que pasa a `CLOSED`, se cierra el panel inferior y desaparecen las lineas horizontales de BUY/TP.

Limitacion actual: si MT5 no entrega detalles del deal de cierre dentro de la ventana configurada, Torum cierra igualmente la posicion desaparecida y usa el ultimo precio conocido para `close_price/current_price/profit`.

## Reglas visuales

- `OPEN`: se muestran linea BUY, linea TP y panel inferior seleccionable.
- `CLOSED`: no se muestran lineas horizontales permanentes ni TP editable.
- `CLOSED`: se muestran marcadores historicos de entrada/cierre si hay fecha/precio suficiente.
- No se puede modificar TP de una posicion cerrada.
- No se puede modificar TP si la linea BUY no esta seleccionada.
