# Strategy Engine

## Regla principal

Una estrategia nunca ejecuta órdenes directamente.

```text
Strategy Plugin
  -> StrategySignal
  -> StrategyRunner
  -> RiskManager
  -> OrderManager
  -> mt5_bridge
  -> MT5
```

Torum V1 se evalúa automáticamente al cerrar una nueva vela M5. La deduplicación por vela y el `HybridLock` por símbolo evitan ejecuciones simultáneas.

## Seguridad

- PAPER es el modo seguro inicial.
- DEMO requiere MT5 conectado y ejecución habilitada.
- LIVE exige `strategy_live_enabled` y las validaciones de trading real.
- Cada señal pasa por DXY, zonas, soportes, ATH, snapshot de riesgo y OrderManager.
- Las señales conservan `strategy_config_id` y `strategy_config_revision`.

## Configuración tipada

`app.strategies.torum_v1_config.TorumV1Params` es la fuente única de verdad. El esquema UI se genera desde el backend y cubre todos los parámetros editables.

La configuración se compone de:

```text
base_params
asset_overrides.XAUUSD
asset_overrides.XAUEUR
enabled_by_symbol
mode_by_symbol
```

La actualización de ambos activos es atómica y usa revisión optimista.

## Flujo Torum V1

```text
Motor y activo
  -> Horario
  -> Noticias
  -> Desbloqueo H2/H3
  -> Pullback M5
  -> Mínimo dentro del rectángulo Torum
  -> Confirmación cerrada
  -> DXY
  -> Soporte S1/S2/S3
  -> Zona ATH y riesgo
  -> Orden y TP
```

## Simulación

```text
POST /api/strategies/torum-v1/simulate
```

Evalúa el estado actual y devuelve una traza estructurada. Nunca envía órdenes.

```text
POST /api/strategies/torum-v1/simulate/history
```

Ejecuta un replay técnico sobre velas M5. No reconstruye rentabilidad, balance/riesgo o DXY históricos.

## Versiones

Cada publicación crea `StrategyConfigVersion` con usuario, revisión, parámetros y nota. Una versión antigua puede restaurarse, creando una revisión nueva sin eliminar el historial.

## Endpoints principales

```text
GET   /api/strategies
GET   /api/strategies/torum-v1/status
GET   /api/strategies/torum-v1/configuration/schema
GET   /api/strategies/torum-v1/configuration
PATCH /api/strategies/torum-v1/configuration
POST  /api/strategies/torum-v1/simulate
POST  /api/strategies/torum-v1/simulate/history
GET   /api/strategies/torum-v1/pullbacks
GET   /api/strategy-configs/{id}/versions
POST  /api/strategy-configs/{id}/versions/{revision}/restore
GET   /api/strategy-signals
GET   /api/strategy-runs
```

## Estado distribuido

Redis es opcional y se usa para:

- lease distribuido por símbolo;
- caché de pullbacks;
- réplica del estado MT5;
- pub/sub de eventos WebSocket.

El fallback local conserva la operativa. El modo single-worker continúa por defecto si los schedulers y el worker de jobs siguen dentro del proceso API.
