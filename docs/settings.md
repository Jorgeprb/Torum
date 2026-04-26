# Ajustes

La pantalla Ajustes concentra configuracion que no debe ocupar la pantalla principal del grafico.

## Lotaje

Regla por defecto:

```text
0.01 lotes por cada 2500 EUR/USD de equity disponible
```

Formula:

```text
base_lot = floor(available_equity / equity_per_0_01_lot) * 0.01
effective_lot = base_lot * multiplier
```

Si no hay equity disponible desde MT5, Torum usa `minimum_lot`.

Campos:

- `lot_per_equity_enabled`
- `equity_per_0_01_lot`, por defecto `2500`
- `minimum_lot`, por defecto `0.01`
- `allow_manual_lot_adjustment`

## Take profit

Por defecto:

```text
default_take_profit_percent = 0.09
```

Para una compra:

```text
TP = entry_price * (1 + default_take_profit_percent / 100)
```

El frontend muestra una vista previa, pero el backend recalcula y valida el TP antes de ejecutar.

## Stop loss

`use_stop_loss=false` por defecto.

Si este ajuste esta desactivado y alguien manda `sl` por API, el risk manager rechaza la orden.

## BUY-only

`long_only=true` por defecto.

La UI principal solo muestra BUY. Si alguien envia `SELL` por API con `long_only=true`, la orden queda rechazada.
