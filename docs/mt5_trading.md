# Trading MT5 desde Torum

El flujo de ordenes es:

```text
PWA -> Backend -> Risk Manager -> Order Manager -> mt5_bridge -> MT5 order_send
```

La PWA nunca llama directamente a MT5.

## Capas de habilitacion

Para DEMO/LIVE deben estar alineadas dos capas:

- Backend: `trading_settings.mt5_order_execution_enabled=true`.
- Bridge: `MT5_ALLOW_ORDER_EXECUTION=true` o habilitado en runtime desde `/settings/order-execution`.

Desde Ajustes, Torum guarda el ajuste del backend e intenta sincronizar el bridge. Si el bridge se reinicia, vuelve al valor de `services/mt5_bridge/.env`.

## Diagnostico de order_send

El bridge registra antes de enviar:

```text
symbol
volume
price
sl
tp
type
type_filling
type_time
deviation
```

Si `order_send` devuelve `None`, ahora registra:

```text
MT5 order_send FAILED:
last_error_code=...
last_error_message=...
request=...
```

Ese `last_error` es la clave para distinguir terminal sin trading, simbolo no operable, volumen invalido, filling mode incompatible o cuenta sin permisos.

## Prechecks del bridge

Antes de `order_send`, el bridge valida:

- `mt5.initialize()`
- `account_info()`
- `terminal_info()`
- `terminal_info.connected`
- `terminal_info.trade_allowed`
- `terminal_info.tradeapi_disabled`
- `symbol_select(symbol, True)`
- `symbol_info.trade_mode`
- `volume_min`, `volume_max`, `volume_step`
- tick actual

Para BUY usa `ASK`. Para cierre de BUY usa `BID`.

## Volumen y filling mode

El bridge ajusta volumen al `volume_min` y `volume_step` del simbolo MT5. Si supera `volume_max`, rechaza con error claro.

El bridge intenta primero el `filling_mode` informado por el simbolo y despues fallback con modos MT5 disponibles, evitando duplicados.

## Resultado esperado

Una ejecucion correcta suele devolver:

```text
retcode=10009 TRADE_RETCODE_DONE
```

No lances una orden LIVE sin confirmar modo, cuenta real y permisos. LIVE sigue protegido por `live_trading_enabled`, confirmacion fuerte y configuracion del bridge.

