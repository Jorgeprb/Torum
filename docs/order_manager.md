# Order Manager

El `OrderManager` es la unica capa backend que convierte una intencion validada en orden.

Fuentes actuales:

- `MANUAL`;
- `STRATEGY`.

## Manual

La PWA manda:

```text
POST /api/orders/manual
```

## Strategy

El `StrategyRunner` llama internamente:

```text
OrderManager.create_strategy_order(...)
```

La orden queda en `orders` con:

- `source=STRATEGY`;
- `strategy_key`;
- `strategy_signal_id`;
- payload completo en `request_payload_json`.

La estrategia no llama al bridge MT5 ni crea posiciones directamente.
