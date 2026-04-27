# Trading manual

Fase 4 implementa operativa manual con este flujo:

```text
PWA -> Backend FastAPI -> Order Manager -> Risk Manager -> mt5_bridge -> MetaTrader 5
```

El frontend nunca habla con MT5 ni con `mt5_bridge` directamente.

## UI movil BUY-only

La pantalla principal movil esta optimizada para comprar rapido:

- solo muestra `BUY`;
- no muestra `SELL`;
- calcula lotaje desde equity;
- permite ajustar lotaje con `+` y `-` como multiplicador de la base;
- previsualiza TP automatico;
- muestra modal de confirmacion;
- avisa claramente que no hay stop loss.

El backend mantiene la regla: si `long_only=true`, una orden `SELL` se rechaza aunque venga por API.

## Lotaje automatico

Regla por defecto:

```text
base_lot = floor(available_equity / 2500) * 0.01
effective_lot = base_lot * multiplier
```

Ejemplo:

- equity `10000` -> base `0.04`;
- multiplier `2` -> `0.08`;
- multiplier `3` -> `0.12`.

El endpoint de soporte es:

```text
GET /api/trading/lot-size?symbol=XAUUSD&multiplier=1
```

## Take profit automatico

Por defecto `default_take_profit_percent=0.09`.

Para BUY:

```text
TP = entry_price * (1 + 0.09 / 100)
```

El frontend puede previsualizarlo, pero el backend lo recalcula usando el ultimo precio disponible antes de guardar/enviar la orden.

## Sin stop loss por defecto

`use_stop_loss=false`.

Si se envia un `sl` cuando ese ajuste esta desactivado, risk manager rechaza la orden.

## Marcadores en grafico

Las ordenes ejecutadas y posiciones se pintan como:

- marcador `BUY`;
- linea de entrada;
- linea de TP si la posicion tiene TP;
- marcador `CLOSE` cuando una posicion cerrada tenga `closed_at`.

## Modos

- `PAPER`: no envia ordenes a MT5. Usa el ultimo tick guardado en Torum, crea la orden y abre una posicion simulada.
- `DEMO`: envia a MT5 solo si el backend tiene estado fresco del bridge y la cuenta detectada es `DEMO`.
- `LIVE`: envia a MT5 solo si la cuenta detectada es `REAL`, `live_trading_enabled=true`, la PWA confirma explicitamente y el bridge permite ejecucion real.

Valores seguros por defecto:

```text
TRADING_MODE=PAPER
LIVE_TRADING_ENABLED=false
MT5_ALLOW_ORDER_EXECUTION=false
MT5_ENABLE_REAL_TRADING=false
```

## PAPER

1. Levanta backend y frontend.
2. Inicia mock market data o el bridge MT5 de ticks para tener precio fresco.
3. Inicia sesion en la PWA.
4. Mantén modo `PAPER`.
5. Envia una orden desde el panel manual.
6. Revisa ordenes y posiciones en la tabla inferior.

Comprobacion por API:

```powershell
$body = @{ username = "admin"; password = "change-admin-password" } | ConvertTo-Json
$login = Invoke-RestMethod -Method Post -ContentType "application/json" -Uri http://localhost:8000/api/v1/auth/login -Body $body
$headers = @{ Authorization = "Bearer $($login.access_token)" }

$order = @{
  internal_symbol = "XAUUSD"
  side = "BUY"
  order_type = "MARKET"
  volume = 0.01
  comment = "Paper manual order"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -ContentType "application/json" -Headers $headers -Uri http://localhost:8000/api/orders/manual -Body $order
Invoke-RestMethod -Headers $headers http://localhost:8000/api/orders
Invoke-RestMethod -Headers $headers http://localhost:8000/api/positions
```

## DEMO

1. Abre MT5 en Windows con cuenta demo.
2. Levanta backend Docker.
3. En `services/mt5_bridge/.env` configura:

```text
MT5_ALLOW_ORDER_EXECUTION=true
MT5_ALLOWED_ACCOUNT_MODES=DEMO
MT5_ENABLE_REAL_TRADING=false
```

4. Arranca el bridge:

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum\services\mt5_bridge
.\.venv\Scripts\Activate.ps1
python -m bridge.main
```

5. Comprueba:

```powershell
Invoke-RestMethod http://localhost:8000/api/mt5/status
Invoke-RestMethod http://127.0.0.1:9100/health
```

6. En la PWA cambia el modo a `DEMO` y confirma el envio.

El backend bloqueara la orden si la cuenta detectada es `REAL`, `UNKNOWN`, si MT5 esta desconectado, si el estado del bridge esta desactualizado o si el precio no es fresco.

## Bloqueo por noticias

Desde Fase 5, el risk manager tambien revisa zonas de no operar.

Si `block_trading_during_news=false`, las zonas se pintan en el grafico y la orden puede ejecutarse con warning.

Si `block_trading_during_news=true`, cualquier orden manual en una zona activa con `blocks_trading=true` se rechaza con un motivo como:

```text
Trading blocked by high-impact news zone: HIGH USD news: Nonfarm Payrolls
```

Configurar por API:

```powershell
$settings = @{
  draw_news_zones_enabled = $true
  block_trading_during_news = $true
  minutes_before = 60
  minutes_after = 60
} | ConvertTo-Json
Invoke-RestMethod -Method Patch -ContentType "application/json" -Headers $headers -Uri http://localhost:8000/api/news/settings -Body $settings
```

## LIVE

LIVE permanece bloqueado por defecto.

Para que una orden LIVE pueda salir en el futuro deben estar alineados todos estos controles:

- Backend: `live_trading_enabled=true`.
- PWA: confirmacion fuerte con checkbox y texto `CONFIRM LIVE`.
- Bridge: `MT5_ALLOW_ORDER_EXECUTION=true`.
- Bridge: `MT5_ENABLE_REAL_TRADING=true`.
- Bridge: `MT5_ALLOWED_ACCOUNT_MODES=DEMO,REAL` o `REAL`.
- MT5: cuenta detectada como `REAL`.

No actives esos valores por accidente. Una cuenta real puede producir perdidas reales.

## Base de datos

Ordenes:

```powershell
docker compose exec -T timescaledb psql -U torum -d torum -c "select id, internal_symbol, mode, side, volume, status, rejection_reason, created_at from orders order by id desc limit 20;"
```

Posiciones:

```powershell
docker compose exec -T timescaledb psql -U torum -d torum -c "select id, internal_symbol, mode, side, volume, open_price, current_price, profit, status from positions order by id desc limit 20;"
```

## Errores MT5 comunes

- `MT5 order execution is disabled`: revisa dos capas. En Ajustes activa `Habilitar ejecucion MT5`; el backend intentara activar tambien el bridge en runtime. Si el bridge acaba de reiniciarse y vuelve a `MT5_ALLOW_ORDER_EXECUTION=false`, guarda el ajuste otra vez o configura `.env` y reinicia el bridge.
- `MT5 terminal trading is disabled`: el bridge ya no bloquea con este mensaje antes de enviar. Ahora lo registra como advertencia y llama a `order_send` para obtener el `retcode` o `last_error` real de MT5.
- `MT5 order_send returned None`: revisa el log del bridge. Ahora imprime `MT5 order_send FAILED` con `last_error_code`, `last_error_message` y el request exacto enviado a MT5.
- `Requested DEMO but MT5 account is REAL`: cambia a cuenta demo o vuelve a `PAPER`.
- `Unsupported filling mode`: el bridge prueba IOC, FOK y RETURN; revisa el simbolo y el broker.
- `No current tick`: mercado cerrado, simbolo no visible en Market Watch o mapeo broker incorrecto.
- `Symbol not available`: revisa `symbol_mappings` o `MT5_FALLBACK_SYMBOL_MAPPINGS`.

## Ajustes nuevos de UX/trading

En Ajustes puedes controlar:

- `Mostrar linea BID`
- `Mostrar linea ASK`
- `Habilitar ejecucion MT5`

La ejecucion MT5 sigue bloqueada si el modo y la cuenta no coinciden, si `LIVE` no tiene confirmacion fuerte, si el bridge esta desconectado o si el risk manager rechaza la orden. `SELL` sigue bloqueado cuando `long_only=true`.

## Cierre y TP desde grafico

- Toca la linea azul de entrada `BUY` para abrir el panel inferior de posicion.
- Pulsa `CERRAR CON BENEFICIO/PERDIDA` para cerrar; Torum pide confirmacion.
- Arrastra la linea verde `TP` para modificar take profit sin popup.

Para BUY:

```text
tp_percent = ((tp_price - open_price) / open_price) * 100
```

El backend valida `tp > open_price`. En DEMO/LIVE se llama al bridge con `TRADE_ACTION_SLTP`. No se envia SL.
