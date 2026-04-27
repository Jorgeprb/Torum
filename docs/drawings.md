# Dibujos

Fase 7 introduce dibujos persistentes sobre el grafico.

## Tipos

- `horizontal_line`: nivel de precio.
- `vertical_line`: momento temporal.
- `trend_line`: dos puntos tiempo/precio.
- `rectangle`: rango temporal y rango de precio.
- `text`: etiqueta en tiempo/precio.
- `manual_zone`: zona manual preparada para uso operativo futuro.

## Persistencia

Los dibujos se guardan en `chart_drawings` como JSON:

```text
user_id
internal_symbol
timeframe
drawing_type
payload_json
style_json
metadata_json
locked
visible
source
created_at
updated_at
deleted_at
```

No se guardan imagenes. No se guarda X/Y de pantalla como fuente principal.

La fuente persistente es:

```text
time + price + payload + style
```

Desde esta fase, `timeframe` queda como campo historico/de procedencia. Los dibujos se consultan por usuario y simbolo, y se pintan en todas las temporalidades recalculando tiempo/precio contra la escala actual.

El frontend convierte esas coordenadas a pixeles con:

- `chart.timeScale().timeToCoordinate(time)`
- `series.priceToCoordinate(price)`

## Crear una linea horizontal

```powershell
$drawing = @{
  internal_symbol = "XAUUSD"
  timeframe = $null
  drawing_type = "horizontal_line"
  name = "Resistencia"
  payload = @{ price = 2325.50; label = "Resistencia" }
  style = @{ color = "#f5c542"; lineWidth = 2 }
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Method Post -ContentType "application/json" -Headers $headers -Uri http://localhost:8000/api/drawings -Body $drawing
```

## Crear una zona manual

```powershell
$zone = @{
  internal_symbol = "XAUUSD"
  timeframe = $null
  drawing_type = "manual_zone"
  name = "Zona manual"
  payload = @{
    time1 = 1777209600
    time2 = $null
    price_min = 2320.0
    price_max = 2335.0
    direction = "BUY"
    label = "Zona de compra manual"
    rules = @{}
    metadata = @{}
  }
  style = @{
    color = "#62d995"
    lineWidth = 2
    backgroundColor = "rgba(98,217,149,0.16)"
  }
} | ConvertTo-Json -Depth 8

Invoke-RestMethod -Method Post -ContentType "application/json" -Headers $headers -Uri http://localhost:8000/api/drawings -Body $zone
```

Si `manual_zone.time2` es `null`, la PWA la pinta extendida hasta el borde derecho visible del grafico.

## PWA

En el dashboard hay una toolbar:

- cursor/select;
- horizontal line;
- vertical line;
- trend line;
- rectangle;
- text;
- manual zone;
- hide/show drawings;
- delete selected.

Para crear:

- linea horizontal, vertical o texto: un click en el grafico;
- tendencia, rectangulo o zona manual: dos clicks.

Si creas un rectangulo en H1 con `time1=10:00` y `time2=11:00`, al cambiar a H2 se ve el mismo rango temporal real. Cambia el ancho visual porque cambia la escala, pero no se guarda ni se reutiliza ningun ancho en pixeles.

## Ocultar y eliminar

El panel `Dibujos` permite:

- seleccionar;
- editar nombre;
- mover objetos directamente sobre el grafico;
- ajustar extremos/bordes cuando el objeto tiene handles;
- borrar el objeto seleccionado desde el boton `Eliminar` sobre el grafico o desde el panel;

## Mover y ajustar

La PWA no guarda pixeles. Cuando arrastras un dibujo, calcula de nuevo `time` y `price` con las escalas actuales:

- `horizontal_line`: arrastre vertical cambia `price`.
- `vertical_line`: arrastre horizontal cambia `time`.
- `trend_line`: arrastre mueve la linea completa; handles permiten ajustar punto 1 o punto 2.
- `rectangle` y `manual_zone`: arrastre mueve la zona; handles de esquina ajustan tiempo/precio.
- `text`: arrastre mueve el punto `time/price`.

Al soltar, se hace `PATCH /api/drawings/{id}`. Si el dibujo esta `locked=true`, no se modifica.
- cambiar color;
- ocultar/mostrar;
- eliminar.

Eliminar usa soft delete: `deleted_at` queda poblado y el dibujo deja de aparecer.

## Integracion futura

Los dibujos quedan preparados para:

- alertas sobre precio tocando una linea/zona;
- estrategias que lean zonas manuales;
- indicadores que generen overlays tipo zona;
- objetos locked de source `INDICATOR`, `NEWS` o `STRATEGY`.

Desde Fase 8, `example_manual_zone_strategy` puede leer `manual_zone` visibles. Por defecto usa `dry_run=true` y no emite orden. Una `manual_zone` no bloquea trading automaticamente.

## Limitaciones actuales

- En movil el icono de lapiz despliega herramientas de dibujo y permite crear objetos con toques sobre el grafico.
- Las herramientas de dos puntos usan primer toque como punto inicial y segundo toque como punto final.
- No hay drag and drop avanzado.
- La edicion numerica completa de payload queda como TODO.
- No hay sincronizacion WebSocket de dibujos entre varios usuarios todavia.
- Los dibujos son por usuario autenticado; no hay sharing entre usuarios.
