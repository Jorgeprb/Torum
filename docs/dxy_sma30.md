# DXY + SMA30

DXY es el indice del dolar. En Torum se usa como activo de analisis para observar fuerza o debilidad relativa del USD.

## Uso

Caso principal:

```text
symbol = DXY
timeframe = D1
indicator = SMA
period = 30
```

SMA30 representa la media simple de los ultimos 30 cierres diarios de DXY.

## Simbolo

Torum crea este mapping por defecto:

```text
internal_symbol = DXY
broker_symbol = DXY
display_name = US Dollar Index
asset_class = INDEX
enabled = true
tradable = false
analysis_only = true
```

DXY aparece en el grafico, pero no puede operarse desde el panel manual.

## DXY sintetico

Torum calcula DXY con velas D1 cerradas de:

```text
EURUSD, USDJPY, GBPUSD, USDCAD, USDSEK, USDCHF
```

Formula:

```text
DXY = 50.14348112
  * EURUSD^-0.576
  * USDJPY^0.136
  * GBPUSD^-0.119
  * USDCAD^0.091
  * USDSEK^0.042
  * USDCHF^0.036
```

Endpoint rapido:

```text
GET /api/market-context/dollar-strength
```

Recalculo manual:

```text
POST /api/market-context/dollar-strength/recompute
```

## mt5_bridge

El bridge no mete DXY en el streaming principal.
Solo expone velas MT5 bajo demanda para los pares usados por DXY.

Fallback local:

```text
MT5_FALLBACK_SYMBOL_MAPPINGS=XAUUSD:XAUUSD,XAUEUR:XAUEUR
```

Si falta algun par, el snapshot queda `UNKNOWN` y muestra el simbolo faltante.

## Abrir DXY D1

1. Abre la PWA.
2. Selecciona `DXY`.
3. Selecciona `D1`.
4. El panel de orden manual mostrara que DXY es solo analisis.
5. El panel de indicadores mostrara la config SMA.

## Activar SMA30

El backend registra por defecto `SMA` y crea config global `DXY/D1/period=30`.

Endpoint:

```text
GET /api/indicators/calculate?symbol=DXY&timeframe=D1&indicator=SMA&period=30&limit=300
```

Si hay al menos 30 velas D1, devuelve puntos de linea. Si hay menos, devuelve la linea vacia y la PWA muestra que faltan cierres.

## Interpretacion

SMA30 se usa como referencia visual y filtro del BOT:

- DXY por encima de SMA30 suele bloquear compras automaticas.
- DXY por debajo de SMA30 permite compras automaticas.
- Si DXY esta por encima pero cae fuerte, puede permitir compras.

El filtro solo afecta al BOT. El usuario manual siempre puede operar.
