# Indicadores

Fase 6 introduce un sistema de indicadores calculados en backend.

La fuente sigue siendo:

```text
ticks -> candles de Torum -> IndicatorEngine -> overlays -> PWA
```

El frontend solo visualiza. No calcula indicadores como fuente principal.

## Plugin

Un plugin vive en:

```text
services/api/app/indicators/plugins/
```

Debe exponer:

- `key`
- `name`
- `version`
- `description`
- `default_params`
- `supported_outputs`
- `calculate(candles, params, context)`

El metodo `calculate` recibe velas Torum y devuelve una salida normalizada.

## Salida tipo linea

```json
{
  "type": "line",
  "name": "SMA30",
  "symbol": "DXY",
  "timeframe": "D1",
  "points": [
    {
      "time": 1777209600,
      "value": 104.23
    }
  ],
  "style": {
    "lineWidth": 2
  }
}
```

## Salida tipo zona

```json
{
  "type": "zone",
  "name": "Custom Operational Zone",
  "symbol": "XAUUSD",
  "timeframe": "H1",
  "zones": []
}
```

Fase 6 incluye `CustomZoneExamplePlugin` como placeholder. No implementa logica operativa real.

## Registrar indicadores

```text
POST /api/indicators/register-defaults
```

El backend tambien registra defaults al arrancar.

## Calcular

```text
GET /api/indicators/calculate?symbol=DXY&timeframe=D1&indicator=SMA&period=30&limit=300
```

## Configuraciones

```text
GET /api/indicator-configs?symbol=DXY&timeframe=D1
POST /api/indicator-configs
PATCH /api/indicator-configs/{id}
DELETE /api/indicator-configs/{id}
```

Se crea una config global por defecto:

```text
DXY + D1 + SMA period=30
```

## Chart overlays

El frontend puede pedir todos los overlays activos:

```text
GET /api/chart/overlays?symbol=DXY&timeframe=D1
```

Respuesta:

- indicadores activos;
- zonas de no operar;
- dibujos persistentes visibles del usuario autenticado;
- base preparada para markers, bandas y zonas operativas futuras.

Los indicadores que devuelvan zonas siguen siendo overlays calculados. No se convierten automaticamente en dibujos persistentes salvo que una fase futura lo defina expresamente.

## Persistencia

SMA30 se calcula bajo demanda desde `candles` porque es liviano. La tabla `indicator_values` queda preparada para indicadores pesados o costosos de recalcular.

## Estrategias

Desde Fase 8, `StrategyContext` puede consumir resultados de `IndicatorEngine`. El ejemplo `example_sma_dxy_filter` lee DXY D1 + SMA30 y devuelve una signal `NONE` con metadata de fuerza/debilidad del dolar.
