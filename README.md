# Torum

Torum es una PWA de trading para oro, integrada con MetaTrader 5 mediante un bridge Python local. La fase actual mejora la interfaz responsive/mobile y mantiene estrategias desactivadas por defecto.

## Decision de arquitectura local

La arquitectura inicial queda fijada asi:

- Windows local:
  - MT5 abierto manualmente.
  - `services/mt5_bridge` corre como proceso Python fuera de Docker.
  - `apps/web` corre fuera de Docker con Vite y `npm run dev`.
- Docker Compose:
  - `api`: backend FastAPI.
  - `timescaledb`: PostgreSQL + TimescaleDB.
  - `redis`: preparado para colas, estado efimero y alertas futuras.
- Acceso remoto:
  - Tailscale/VPN.
  - Backend escuchando en `0.0.0.0` mediante `API_BIND_HOST=0.0.0.0`.
  - Frontend escuchando en `0.0.0.0` con `npm run dev:host` cuando se use Tailscale.

El frontend no ejecuta ordenes directamente. Toda intencion de orden pasara por el backend, y el backend sera quien valide riesgo, modo de ejecucion y coherencia con MT5 antes de hablar con el bridge.

## Decision de datos de mercado

MT5 mandara ticks, no velas.

Torum guarda ticks crudos en TimescaleDB y construye internamente las velas `M1`, `M5`, `H1`, `H2`, `H4`, `D1` y `W1`.

## Decision de noticias

Torum no depende de scraping fragil como unica fuente de calendario economico. Fase 5 permite importar noticias por JSON/CSV, normalizarlas, crear zonas de no operar y bloquear trading manual si el usuario lo activa.

Por defecto:

- se pintan zonas de noticias;
- no se bloquea trading;
- filtro inicial `USD` + `HIGH`;
- ventana 60 minutos antes y 60 minutos despues.

## Decision de indicadores

Los indicadores se calculan en backend desde velas de Torum. El frontend solo pinta overlays.

Fase 6 incluye:

- DXY como `analysis_only`;
- SMA generico con periodo configurable;
- config global `DXY + D1 + SMA30`;
- endpoint comun `/api/chart/overlays`.

## Decision de dibujos

Los dibujos se guardan como JSON en `chart_drawings`. La persistencia usa coordenadas de mercado:

- tiempo Unix/ISO normalizado;
- precio;
- payload por tipo;
- estilo y metadata JSON.

No se guardan imagenes ni coordenadas de pantalla. La PWA recalcula pixeles al hacer zoom/scroll usando Lightweight Charts.

## Decision de estrategias

Las estrategias no ejecutan ordenes directamente. Generan `StrategySignal` y pasan por:

```text
StrategyRunner -> RiskManager -> OrderManager -> mt5_bridge
```

Por defecto:

- `strategies_enabled=false`;
- `strategy_live_enabled=false`;
- configs nuevas desactivadas;
- modo recomendado `PAPER`.

## Decision de interfaz responsive/mobile

La pantalla principal es mobile-first e inspirada en proporciones de terminal movil de trading, sin copiar marcas:

- fondo negro;
- grafico como superficie principal;
- top bar compacta con menu, timeframe, estado y accesos rapidos;
- drawer lateral para cuenta, navegacion, estrategias, indicadores y ajustes;
- panel de compra compacto;
- BUY-only por defecto;
- calculo de lote por equity;
- TP automatico por defecto de `0.09%`;
- sin stop loss por defecto.
- lineas dinamicas `BID` y `ASK` activables desde Ajustes;
- zoom/pan del grafico respetado al llegar ticks, con boton `Seguir precio`.

El backend tambien valida estas reglas. Si `long_only=true`, una orden `SELL` enviada por API queda rechazada.

## Decision de alertas

Fase 9 solo soporta alertas de precio `BELOW`:

```text
price <= target_price
```

Las alertas activas se pintan como lineas horizontales. Al dispararse pasan a `TRIGGERED`, desaparecen del grafico, quedan en historico y pueden enviar push PWA al usuario dueño de la alerta.

En movil, el boton de alerta es toggle y el toque sobre el grafico crea la alerta con coordenada de precio, no con pixeles.

## Diagnostico de precio

Para comparar Torum con MT5 usa `GET /api/market/latest-tick?symbol=XAUUSD` o Ajustes -> Diagnostico de mercado. Torum muestra `BID`, `ASK`, `source`, `broker_symbol`, edad del tick y `Candle close`.

Desde esta fase, `CANDLE_PRICE_SOURCE=BID` por defecto. Una diferencia grande con MT5 suele indicar mock activo, `broker_symbol` distinto, tick viejo o estar comparando `MID/CLOSE` contra `BID`. Ver [market_price_diagnostics.md](docs/market_price_diagnostics.md) y [price_consistency.md](docs/price_consistency.md).

Para diagnostico de ejecucion MT5 y errores `order_send=None`, ver [mt5_trading.md](docs/mt5_trading.md).

## Grafico, posiciones e historial

La fase actual mejora el grafico movil:

- dibujos y alertas seleccionables, movibles y borrables;
- autoescala/recentrado por simbolo y timeframe sin resetear zoom en cada tick;
- lineas de posicion abiertas: entrada BUY azul y TP verde;
- modificacion de TP arrastrando la linea verde;
- cierre de posicion desde panel inferior con confirmacion;
- sincronizacion basica de posiciones abiertas/cerradas desde MT5;
- historial en burger menu y endpoint `/api/trade-history`.

Ver [positions.md](docs/positions.md), [trade_history.md](docs/trade_history.md) y [drawings.md](docs/drawings.md).

Los ticks guardan `time_msc` y Torum resuelve el ultimo precio por `time_msc DESC`. El precio visible principal debe ser `latestTick.bid`; `candle.close` queda para velas/historico.

## Reconexion y resync

La PWA usa un WebSocket manager centralizado con heartbeat `ping/pong`, backoff y deteccion de datos `stale`. Al volver de segundo plano, recuperar red o reconectar el socket, Torum recarga velas, ultimo tick, estado MT5, posiciones, historial, alertas y overlays.

En `DEMO` y `LIVE`, las acciones de compra, cierre y modificacion de TP se bloquean si el stream esta desconectado, reconectando o desactualizado. Ver [reconnection.md](docs/reconnection.md).

La sincronizacion de cierres MT5 usa `positions_get()` como verdad de posiciones abiertas y `history_deals_get()` para completar cierres por `deal.position_id`, guardando `close_price`, `closed_at`, `profit`, `swap`, `commission` y `closing_deal_ticket`.

Para push se usan variables VAPID en `.env`:

```text
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=mailto:admin@torum.dev
```

## Roles

La fase 1 soporta unicamente dos roles:

- `admin`
- `trader`

No existe rol `viewer` en esta version por decision del proyecto.

## Requisitos

- Windows.
- Docker Desktop.
- Node.js 20+.
- npm.
- Python 3.11+ para ejecutar `services/mt5_bridge`.

## Arranque local

Desde PowerShell:

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum
Copy-Item .env.example .env
docker compose up --build
```

En otra terminal:

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum\apps\web
Copy-Item .env.example .env.local
npm install
npm run dev
```

Abrir:

```text
http://localhost:5173
```

## Migraciones

El contenedor `api` ejecuta automaticamente:

```powershell
alembic upgrade head
```

Si ya tenias la fase 1 corriendo:

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum
docker compose up -d --build api
```

Credenciales iniciales, definidas en `.env`:

```text
Usuario admin:  admin
Password admin: change-admin-password

Usuario trader:  trader
Password trader: change-trader-password
```

Cambia esas passwords antes de usar Torum fuera de tu maquina local.

## Pruebas rapidas

Backend:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/v1/system/status
```

Iniciar mock market data:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/mock-market/start
```

Parar mock market data:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/mock-market/stop
```

Consultar velas generadas desde ticks:

```powershell
Invoke-RestMethod "http://localhost:8000/api/candles?symbol=XAUUSD&timeframe=M1&limit=20"
```

Login por API:

```powershell
$body = @{ username = "admin"; password = "change-admin-password" } | ConvertTo-Json
Invoke-RestMethod -Method Post -ContentType "application/json" -Uri http://localhost:8000/api/v1/auth/login -Body $body
```

Guardar el token para llamadas protegidas:

```powershell
$login = Invoke-RestMethod -Method Post -ContentType "application/json" -Uri http://localhost:8000/api/v1/auth/login -Body $body
$headers = @{ Authorization = "Bearer $($login.access_token)" }
```

Enviar orden PAPER:

```powershell
$order = @{
  internal_symbol = "XAUUSD"
  side = "BUY"
  order_type = "MARKET"
  volume = 0.01
  comment = "Paper manual order"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -ContentType "application/json" -Headers $headers -Uri http://localhost:8000/api/orders/manual -Body $order
```

Calcular lotaje automatico:

```powershell
Invoke-RestMethod -Headers $headers "http://localhost:8000/api/trading/lot-size?symbol=XAUUSD&multiplier=1"
```

Enviar compra PAPER con TP automatico y sin SL:

```powershell
$order = @{
  internal_symbol = "XAUUSD"
  side = "BUY"
  order_type = "MARKET"
  volume = 0.01
  sl = $null
  tp_percent = 0.09
  comment = "Manual BUY from Torum mobile"
  client_confirmation = @{
    confirmed = $true
    mode_acknowledged = "PAPER"
    no_stop_loss_acknowledged = $true
  }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -ContentType "application/json" -Headers $headers -Uri http://localhost:8000/api/orders/manual -Body $order
```

Listar ordenes y posiciones:

```powershell
Invoke-RestMethod -Headers $headers http://localhost:8000/api/orders
Invoke-RestMethod -Headers $headers http://localhost:8000/api/positions
```

Importar noticias de ejemplo:

```powershell
$body = Get-Content docs\examples\news_events_us_high_impact.json -Raw
Invoke-RestMethod -Method Post -ContentType "application/json" -Headers $headers -Uri http://localhost:8000/api/news/import/json -Body $body
```

Configurar bloqueo por noticias:

```powershell
$settings = @{
  block_trading_during_news = $true
  draw_news_zones_enabled = $true
  minutes_before = 60
  minutes_after = 60
} | ConvertTo-Json
Invoke-RestMethod -Method Patch -ContentType "application/json" -Headers $headers -Uri http://localhost:8000/api/news/settings -Body $settings
```

Calcular SMA30 de DXY:

```powershell
Invoke-RestMethod "http://localhost:8000/api/indicators/calculate?symbol=DXY&timeframe=D1&indicator=SMA&period=30&limit=300"
```

Crear una linea horizontal:

```powershell
$drawing = @{
  internal_symbol = "XAUUSD"
  timeframe = "H1"
  drawing_type = "horizontal_line"
  name = "Resistencia"
  payload = @{ price = 2325.50; label = "Resistencia" }
  style = @{ color = "#f5c542"; lineWidth = 2 }
} | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Post -ContentType "application/json" -Headers $headers -Uri http://localhost:8000/api/drawings -Body $drawing
```

Listar dibujos y overlays:

```powershell
Invoke-RestMethod -Headers $headers "http://localhost:8000/api/drawings?symbol=XAUUSD&timeframe=H1&include_hidden=true"
Invoke-RestMethod -Headers $headers "http://localhost:8000/api/chart/overlays?symbol=XAUUSD&timeframe=H1"
```

Registrar y ejecutar estrategia de ejemplo:

```powershell
Invoke-RestMethod -Method Post -Headers $headers http://localhost:8000/api/strategies/register-defaults

$settings = @{ strategies_enabled = $true; strategy_live_enabled = $false; default_mode = "PAPER" } | ConvertTo-Json
Invoke-RestMethod -Method Patch -ContentType "application/json" -Headers $headers -Uri http://localhost:8000/api/strategy-settings -Body $settings

$config = @{
  strategy_key = "example_sma_dxy_filter"
  internal_symbol = "XAUUSD"
  timeframe = "H1"
  enabled = $true
  mode = "PAPER"
  params_json = @{}
} | ConvertTo-Json -Depth 6
$createdConfig = Invoke-RestMethod -Method Post -ContentType "application/json" -Headers $headers -Uri http://localhost:8000/api/strategy-configs -Body $config

Invoke-RestMethod -Method Post -Headers $headers "http://localhost:8000/api/strategies/run/$($createdConfig.id)"
```

Documentacion OpenAPI:

```text
http://localhost:8000/docs
```

## Tailscale

Para usar la app desde otro dispositivo conectado a Tailscale:

1. En `.env`, mantener o establecer:

```text
API_BIND_HOST=0.0.0.0
TAILSCALE_ENABLED=true
PUBLIC_HOST=<ip-o-dns-tailscale>
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://<ip-o-dns-tailscale>:5173
```

2. En `apps/web/.env.local`:

```text
VITE_API_BASE_URL=http://<ip-o-dns-tailscale>:8000
VITE_WS_BASE_URL=ws://<ip-o-dns-tailscale>:8000
VITE_PUBLIC_HOST=<ip-o-dns-tailscale>
VITE_TAILSCALE_MODE=true
```

3. Arrancar el frontend escuchando en todas las interfaces:

```powershell
npm run dev:host
```

## Estado actual

Incluido:

- Monorepo base.
- Docker Compose para API, TimescaleDB y Redis.
- Backend FastAPI con migraciones Alembic.
- Autenticacion con hash de password y JWT.
- Usuarios iniciales `admin` y `trader`.
- Frontend React/TypeScript/Vite/PWA.
- Login y dashboard oscuro inicial.
- Documentacion inicial.
- Modelo de simbolos y mapeo broker.
- Ticks en TimescaleDB.
- Velas generadas desde ticks.
- Mock market data backend.
- WebSocket `ws://host/ws/market/{symbol}/{timeframe}`.
- Grafico Lightweight Charts.
- Bridge MT5 real para lectura de ticks.
- Estado MT5 en `/api/mt5/status`.
- Deduplicacion de ticks al reintentar/reiniciar con lookback.
- Trading manual desde PWA.
- Configuracion `PAPER` / `DEMO` / `LIVE` en backend.
- Risk manager inicial para modo, cuenta MT5, simbolo, volumen, precio fresco y SL/TP basico.
- Ordenes y posiciones persistidas en base de datos.
- Servidor HTTP local del `mt5_bridge` para ejecucion de ordenes preparado con `MT5_ALLOW_ORDER_EXECUTION=false` por defecto.
- News engine con importacion JSON/CSV.
- Zonas de no operar pintadas sobre el grafico.
- Bloqueo operativo por noticias integrado en risk manager, desactivado por defecto.
- DXY como activo de analisis no operable.
- Indicadores backend con plugin SMA.
- SMA30 DXY/D1 como overlay de grafico.
- Base para indicadores tipo linea, zona, marker, banda y shape.
- Dibujos persistentes por usuario/simbolo/timeframe.
- Herramientas iniciales: horizontal, vertical, tendencia, rectangulo, texto y zona manual.
- `manual_zone` preparada para alertas/estrategias futuras, sin bloquear trading todavia.
- `/api/chart/overlays` combina indicadores, zonas de noticias y dibujos visibles del usuario autenticado.
- Strategy engine base con registry, configs, settings, signals y runs.
- Estrategias de ejemplo `example_sma_dxy_filter` y `example_manual_zone_strategy`.
- Runner manual integrado con risk manager y order manager.
- UI responsive/mobile-first con drawer lateral, panel BUY-only, lotaje por equity y marcadores de operacion en grafico.
- Endpoint `/api/trading/lot-size` para calcular lotaje desde equity disponible.
- Settings `long_only`, `default_take_profit_percent`, `use_stop_loss`, `equity_per_0_01_lot` y `minimum_lot`.
- Alertas de precio `BELOW` persistentes, dibujadas en grafico y evaluadas desde ticks.
- Push subscriptions PWA y Web Push con VAPID.

Pendiente para fases posteriores:

- Scheduler continuo de estrategias.
- Alertas avanzadas por indicadores/estrategias.

## Contrato mt5_bridge Fase 3

```text
POST /api/ticks/batch
```

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

El backend valida simbolo, guarda ticks, actualiza velas afectadas y emite `candle_update` por WebSocket.

## Arrancar mt5_bridge real

Con MT5 abierto y backend levantado:

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum\services\mt5_bridge
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m bridge.main
```

Por seguridad, el bridge arranca con ejecucion de ordenes desactivada:

```text
MT5_ALLOW_ORDER_EXECUTION=false
```

Para probar DEMO real, con MT5 abierto en cuenta demo, puedes activar desde Ajustes `Habilitar ejecucion MT5`. El backend guarda `mt5_order_execution_enabled` y sincroniza el runtime del bridge si esta accesible. Tambien puedes dejarlo activo por `.env`:

```text
MT5_ALLOW_ORDER_EXECUTION=true
MT5_ALLOWED_ACCOUNT_MODES=DEMO
MT5_ENABLE_REAL_TRADING=false
```

LIVE queda bloqueado por defecto por el backend y por el bridge. No actives `LIVE` sin revisar `docs/trading_manual.md`.

Estado MT5:

```powershell
Invoke-RestMethod http://localhost:8000/api/mt5/status
```

Estado del servidor local de ordenes del bridge:

```powershell
Invoke-RestMethod http://127.0.0.1:9100/health
```
