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

## Broker symbol en MT5

Cada broker puede llamar distinto al indice:

- `DXY`
- `USDX`
- `USDIDX`
- `US Dollar Index`

En MT5:

1. Abre Market Watch.
2. Click derecho.
3. Selecciona Symbols.
4. Busca `DXY`, `USDX` o `Dollar`.
5. Activa el simbolo si existe.
6. Copia el nombre exacto en `symbol_mappings.broker_symbol`.

Si tu broker no ofrece DXY, Torum necesitara un proveedor externo de datos en una fase futura.

## mt5_bridge

El bridge lee todos los simbolos `enabled`, incluso si `tradable=false`.

Si DXY existe en `symbol_mappings` y el broker_symbol es correcto, el bridge intentara leer ticks y Torum construira velas.

Fallback local:

```text
MT5_FALLBACK_SYMBOL_MAPPINGS=XAUUSD:XAUUSD,XAUEUR:XAUEUR,XAUAUD:XAUAUD,XAUJPY:XAUJPY,DXY:DXY
```

Si el broker no tiene el simbolo, el bridge registrara warning y seguira con el resto.

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

SMA30 no es una señal automatica. Se usa como referencia visual:

- DXY por encima de SMA30 puede sugerir dolar relativamente fuerte.
- DXY por debajo de SMA30 puede sugerir dolar relativamente debil.

La decision de trading sigue fuera del indicador y no dispara ordenes.
