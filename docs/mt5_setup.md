# MT5

MT5 queda fuera de Docker por decision de arquitectura inicial.

Desde la Fase 3:

- MT5 debe estar abierto en Windows.
- La cuenta activa determinara si el bridge esta conectado a demo o real.
- El backend bloqueara incoherencias entre `TRADING_MODE` y tipo de cuenta.
- El bridge Python usara el paquete `MetaTrader5`.
- El bridge mandara ticks a `POST /api/ticks/batch`.
- El bridge no mandara velas. Torum construye las velas desde ticks.
- Las ordenes manuales salen solo desde backend hacia el servidor HTTP local del bridge.

## Fase 3: bridge real

Arranque:

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum\services\mt5_bridge
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m bridge.main
```

Comprobaciones:

```powershell
Invoke-RestMethod http://localhost:8000/api/mt5/status
Invoke-RestMethod "http://localhost:8000/api/ticks?symbol=XAUUSD&limit=5"
Invoke-RestMethod "http://localhost:8000/api/candles?symbol=XAUUSD&timeframe=M1&limit=20"
```

No usar funciones de velas MT5 como fuente principal:

- no `copy_rates_from`
- no `copy_rates_from_pos`
- no `copy_rates_range`

El bridge usa `copy_ticks_range` y fallback `copy_ticks_from`.

## Fase 4: ordenes manuales

El bridge arranca un servidor local en:

```text
http://127.0.0.1:9100
```

Comprobar health:

```powershell
Invoke-RestMethod http://127.0.0.1:9100/health
```

Por defecto no ejecuta ordenes:

```text
MT5_ALLOW_ORDER_EXECUTION=false
MT5_ENABLE_REAL_TRADING=false
```

Para probar DEMO con MT5 ya abierto en cuenta demo:

```text
MT5_ALLOW_ORDER_EXECUTION=true
MT5_ALLOWED_ACCOUNT_MODES=DEMO
MT5_ENABLE_REAL_TRADING=false
```

Para permitir que el mismo bridge pueda enviar ordenes tanto con cuenta DEMO como con cuenta REAL, configura:

```text
MT5_ALLOW_ORDER_EXECUTION=true
MT5_ALLOWED_ACCOUNT_MODES=DEMO,REAL
MT5_ENABLE_REAL_TRADING=true
MT5_MARKET_DATA_ONLY=false
```

El modo seleccionado en Torum debe seguir coincidiendo con la cuenta activa: `DEMO` con cuenta demo y `LIVE` con cuenta real. Torum no salta el risk manager ni la confirmacion fuerte de LIVE.

Desde la app tambien puedes activar/desactivar la ejecucion en Ajustes. Torum guarda `mt5_order_execution_enabled` en backend y llama al servidor HTTP local del bridge:

```text
PATCH http://127.0.0.1:9100/settings/order-execution
```

Si el bridge no esta levantado, activar desde la app falla con un mensaje claro. Si el bridge se reinicia con `MT5_ALLOW_ORDER_EXECUTION=false`, vuelve a guardar el ajuste o cambia `.env` y reinicia conscientemente.

## Diagnostico de simbolos y ticks

Al arrancar, el bridge escribe en logs:

- `internal_symbol -> broker_symbol`;
- resultado de `symbol_select`;
- `digits`, `point`, `trade_mode`, `visible`, `description`;
- resumen periodico de bid/ask por simbolo.

Configura la frecuencia:

```text
MT5_DIAGNOSTIC_LOG_INTERVAL_SECONDS=5
```

Usa esto para confirmar que Torum esta leyendo exactamente el mismo simbolo que tienes abierto en MT5.

Si `order_send` devuelve error, revisa:

- modo de cuenta detectado en `/api/mt5/status`;
- simbolo broker en `symbol_mappings`;
- visibilidad del simbolo en Market Watch;
- volumen minimo/lote permitido por el broker;
- modo de llenado aceptado por el broker.

## Sincronizacion de posiciones

El bridge arranca tambien un sincronizador de posiciones. Cada pocos segundos llama `positions_get()` y publica el estado al backend:

```text
POST /api/mt5/positions/sync
```

Configura el intervalo:

```text
MT5_POSITION_SYNC_INTERVAL_SECONDS=3
```

`positions_get()` manda las posiciones abiertas reales. Ademas, el bridge consulta `history_deals_get()` en una ventana configurable y manda al backend los deals de cierre con `DEAL_ENTRY_OUT`, `DEAL_ENTRY_INOUT` y `DEAL_ENTRY_OUT_BY`.

```text
MT5_DEALS_HISTORY_LOOKBACK_DAYS=14
```

Si cierras una posicion manualmente desde MT5, en el siguiente ciclo Torum detecta que el ticket ya no esta en `positions_get()`, busca el cierre por `deal.position_id`, marca la posicion como `CLOSED`, guarda precio/hora/profit/swap/commission/ticket de deal y la mueve al historial. Si `positions_get()` falla, el bridge no envia una lista vacia para evitar cerrar posiciones por error.

LIVE no debe activarse por accidente. Requiere cambiar controles en backend, PWA y bridge.

## DXY

Desde Fase 6, Torum incluye `DXY` como activo de analisis:

```text
internal_symbol=DXY
tradable=false
analysis_only=true
```

El bridge intentara leer ticks de DXY si el simbolo esta `enabled` y el broker_symbol existe en MT5.

Para encontrar el nombre exacto:

1. Abre MT5.
2. Abre Market Watch.
3. Click derecho -> Symbols.
4. Busca `DXY`, `USDX` o `Dollar`.
5. Activa el simbolo.
6. Actualiza `broker_symbol` en Torum si tu broker usa otro nombre.

El bridge no usa velas MT5 para DXY. Lee ticks y Torum construye D1 desde esos ticks. Si el broker no ofrece DXY, se necesitara un proveedor externo en el futuro.
