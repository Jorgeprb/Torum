# Strategy Engine

Fase 8 introduce la estructura base para estrategias automaticas.

## Regla principal

Una estrategia nunca ejecuta ordenes directamente.

```text
Strategy Plugin
  -> StrategySignal
  -> StrategyRunner
  -> RiskManager
  -> OrderManager
  -> mt5_bridge
  -> MT5
```

En esta fase las estrategias quedan desactivadas por defecto y el modo seguro es `PAPER`.

## Strategy Plugin

Un plugin vive en:

```text
services/api/app/strategies/plugins/
```

Debe declarar `key`, `name`, `version`, `description`, `default_params`, `supported_symbols`, `supported_timeframes`, `required_indicators`, `required_context` y `generate_signal(context)`.

## Signal

Una signal normalizada contiene:

```json
{
  "strategy_key": "example_manual_zone_strategy",
  "internal_symbol": "XAUUSD",
  "timeframe": "H1",
  "side": "BUY",
  "signal_type": "ENTRY",
  "confidence": 0.5,
  "entry_type": "MARKET",
  "suggested_volume": 0.01,
  "reason": "Example signal generated inside manual zone",
  "metadata": {}
}
```

Tipos: `ENTRY`, `EXIT`, `MODIFY`, `NONE`.

## Modos

- `PAPER`: simula mediante el `OrderManager`.
- `DEMO`: preparado, requiere MT5 demo conectado y validaciones de riesgo.
- `LIVE`: bloqueado por defecto.

Flags de seguridad:

```text
strategy_settings.strategies_enabled = false
strategy_settings.strategy_live_enabled = false
```

## Endpoints

```text
GET /api/strategies
POST /api/strategies/register-defaults
GET /api/strategy-configs
POST /api/strategy-configs
PATCH /api/strategy-configs/{id}
DELETE /api/strategy-configs/{id}
GET /api/strategy-settings
PATCH /api/strategy-settings
POST /api/strategies/run
POST /api/strategies/run/{config_id}
GET /api/strategy-signals
GET /api/strategy-runs
```

## Estrategias de ejemplo

`example_sma_dxy_filter` lee DXY D1 y SMA30 calculado por backend. Devuelve `NONE` con metadata `STRONG`, `WEAK`, `NEUTRAL` o `UNKNOWN`.

`example_manual_zone_strategy` lee dibujos `manual_zone` visibles del usuario. Con `dry_run=true` devuelve `NONE`; con `dry_run=false` puede generar `ENTRY` en PAPER si el precio actual esta dentro de una zona BUY/SELL.

## Contexto

`StrategyContext` puede incluir velas de Torum, ultimo tick/precio, DXY/SMA30, no_trade_zones activas, dibujos `manual_zone`, posiciones abiertas, parametros y modo.

No usa datos del frontend ni velas de MT5.

## Crear una estrategia nueva

1. Crear plugin en `services/api/app/strategies/plugins/`.
2. Implementar `generate_signal(context)`.
3. Registrar el plugin en `strategy_registry`.
4. Ejecutar `POST /api/strategies/register-defaults`.
5. Crear una `strategy_config`.
6. Activar `strategies_enabled`.
7. Ejecutar manualmente con `POST /api/strategies/run/{config_id}`.

## Automatizacion continua futura

Fase 8 solo ejecuta manualmente. Un scheduler futuro podria llamar `StrategyRunner` desde APScheduler, Celery/RQ con Redis o un worker dedicado.
