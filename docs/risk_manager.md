# Risk Manager

El `RiskManager` valida toda orden antes de que llegue al bridge MT5.

Fase 8 mantiene la misma capa para ordenes manuales y ordenes originadas por estrategias.

## Reglas actuales

- modo `PAPER` / `DEMO` / `LIVE`;
- trading pausado;
- simbolo habilitado;
- `tradable=true`;
- bloqueo de DXY si `analysis_only=true`;
- volumen positivo;
- volumen maximo si existe;
- precio fresco;
- SL/TP basicos;
- bloqueo por noticias si esta activado;
- coherencia de MT5 para DEMO/LIVE;
- LIVE manual desactivado por defecto;
- LIVE de estrategias desactivado por defecto.

## Estrategias

`evaluate_strategy_order` reutiliza `evaluate` y añade:

- `strategy_settings.strategies_enabled=true`;
- `strategy_settings.strategy_live_enabled=true` para modo LIVE.

La estrategia no evita el risk manager. Si una signal se rechaza, queda registrada como `REJECTED_BY_RISK`.
