# Torum MT5 Bridge

Bridge Python local para leer ticks crudos desde MetaTrader 5 y enviarlos al backend de Torum. Desde Fase 4 tambien expone un servidor HTTP local para que el backend solicite ordenes manuales, con ejecucion desactivada por defecto.

## Regla critica

MT5 no manda velas a Torum.

El bridge usa ticks:

- `copy_ticks_range`
- fallback `copy_ticks_from`
- `symbol_info_tick` solo queda disponible en el cliente, no como fuente principal del loop

No se usan `copy_rates_from`, `copy_rates_from_pos` ni `copy_rates_range`.

## Requisitos

- Windows.
- Python 3.11+ recomendado.
- MetaTrader 5 instalado.
- MT5 abierto y con sesion iniciada.
- Backend Torum corriendo.

## Instalacion

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum\services\mt5_bridge
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

## Configuracion

Edita `.env`:

```text
TORUM_API_BASE_URL=http://127.0.0.1:8000
MT5_ALLOWED_ACCOUNT_MODES=DEMO
MT5_BRIDGE_HOST=127.0.0.1
MT5_BRIDGE_PORT=9100
MT5_ALLOW_ORDER_EXECUTION=false
MT5_ENABLE_REAL_TRADING=false
MT5_FALLBACK_SYMBOL_MAPPINGS=XAUUSD:XAUUSDm,XAUEUR:XAUEUR,XAUAUD:XAUAUD,XAUJPY:XAUJPY,DXY:DXY
```

Si tu broker usa `GOLD`:

```text
MT5_FALLBACK_SYMBOL_MAPPINGS=XAUUSD:GOLD,XAUEUR:XAUEUR,XAUAUD:XAUAUD,XAUJPY:XAUJPY,DXY:DXY
```

El bridge primero intenta leer mapeos desde:

```text
GET /api/symbols
```

Si el backend no esta disponible, usa `MT5_FALLBACK_SYMBOL_MAPPINGS`.

Desde Fase 6, DXY se carga como activo `analysis_only`. El bridge debe intentar leer sus ticks si el simbolo esta `enabled`, aunque `tradable=false`; si tu broker usa `USDX`, `DOLLARINDEX` u otro nombre, ajusta `broker_symbol` en `/api/symbols` o en el fallback local.

## Arranque

Con backend ya levantado:

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum\services\mt5_bridge
.\.venv\Scripts\Activate.ps1
python -m bridge.main
```

Opciones utiles:

```powershell
python -m bridge.main --once
python -m bridge.main --symbols XAUUSD,XAUEUR
python -m bridge.main --log-level DEBUG
python -m bridge.main --market-data-only
```

El servidor local del bridge queda disponible en:

```text
http://127.0.0.1:9100
```

Endpoints:

- `GET /health`
- `GET /account`
- `GET /positions`
- `POST /orders/market`
- `POST /positions/{ticket}/close`

El backend es el unico cliente esperado de esos endpoints.

## Contrato con backend

Endpoint:

```text
POST /api/ticks/batch
```

Payload:

```json
{
  "source": "MT5",
  "account": {
    "login": 123456,
    "server": "ICMarketsSC-Demo",
    "currency": "USD",
    "company": "IC Markets",
    "trade_mode": "DEMO"
  },
  "ticks": [
    {
      "internal_symbol": "XAUUSD",
      "broker_symbol": "XAUUSDm",
      "time": "2026-04-26T12:34:56.123Z",
      "bid": 2325.12,
      "ask": 2325.34,
      "last": null,
      "volume": 0
    }
  ]
}
```

## Comprobaciones

Estado backend:

```powershell
Invoke-RestMethod http://localhost:8000/api/health
Invoke-RestMethod http://localhost:8000/api/mt5/status
```

Ticks MT5 en TimescaleDB:

```powershell
docker compose exec -T timescaledb psql -U torum -d torum -c "select internal_symbol, broker_symbol, source, count(*), max(time) from ticks where source='MT5' group by internal_symbol, broker_symbol, source order by internal_symbol;"
```

Velas derivadas:

```powershell
docker compose exec -T timescaledb psql -U torum -d torum -c "select internal_symbol, timeframe, count(*), max(time) from candles group by internal_symbol, timeframe order by internal_symbol, timeframe;"
```

PWA:

```text
http://localhost:5173
```

El grafico debe seguir usando `GET /api/candles` y `ws://host/ws/market/{symbol}/{timeframe}`.

## Cuenta demo/real

Fase 4 permite ejecucion manual solo si se habilita de forma explicita.

Si detecta cuenta REAL, el bridge imprime una advertencia fuerte. Con:

```text
MT5_ALLOWED_ACCOUNT_MODES=DEMO
MT5_MARKET_DATA_ONLY=true
MT5_ALLOW_ORDER_EXECUTION=false
```

puede continuar mandando datos de mercado, pero no habilita trading.

Para probar DEMO:

```text
MT5_ALLOW_ORDER_EXECUTION=true
MT5_ALLOWED_ACCOUNT_MODES=DEMO
MT5_ENABLE_REAL_TRADING=false
```

Para LIVE futuro deben cambiarse conscientemente tambien los controles del backend y de la PWA. No se recomienda activarlo hasta completar hardening de riesgo.

## Contrato de orden manual

El backend llama:

```text
POST /orders/market
```

```json
{
  "internal_symbol": "XAUUSD",
  "broker_symbol": "XAUUSDm",
  "mode": "DEMO",
  "side": "BUY",
  "order_type": "MARKET",
  "volume": 0.01,
  "sl": 2320.0,
  "tp": 2340.0,
  "deviation_points": 20,
  "magic_number": 260426,
  "comment": "Manual order from Torum"
}
```

Respuesta esperada:

```json
{
  "ok": true,
  "retcode": 10009,
  "comment": "done",
  "order": 123,
  "deal": 456,
  "position": 789,
  "price": 2325.12,
  "volume": 0.01,
  "raw": {}
}
```

## Problemas comunes

- MT5 no abierto: `MT5 initialize failed`.
- Cuenta no conectada: `account_info failed`.
- Simbolo no encontrado: revisa `symbol_mappings` en backend o `MT5_FALLBACK_SYMBOL_MAPPINGS`.
- No llegan ticks: mercado cerrado, simbolo sin actividad o no visible en Market Watch.
- Backend no accesible: revisa `TORUM_API_BASE_URL` y Docker.
- Tailscale: usa la IP/DNS Tailscale en `TORUM_API_BASE_URL`.
- Ordenes rechazadas: revisa `MT5_ALLOW_ORDER_EXECUTION`, modo de cuenta y `MT5_ALLOWED_ACCOUNT_MODES`.
- Broker usa sufijos: `XAUUSDm`, `XAUUSD.`, `GOLD`; ajusta el mapeo.
