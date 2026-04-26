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

Si `order_send` devuelve error, revisa:

- modo de cuenta detectado en `/api/mt5/status`;
- simbolo broker en `symbol_mappings`;
- visibilidad del simbolo en Market Watch;
- volumen minimo/lote permitido por el broker;
- modo de llenado aceptado por el broker.

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
