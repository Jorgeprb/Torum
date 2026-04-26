# News Engine

Fase 5 implementa noticias economicas y zonas de no operar.

## Conceptos

`news_event` es una noticia normalizada:

- fuente;
- pais;
- divisa;
- impacto;
- titulo;
- hora UTC;
- previous, forecast y actual si existen;
- payload bruto para auditoria.

`no_trade_zone` es una ventana temporal asociada a un simbolo:

- inicio;
- fin;
- motivo;
- si esta habilitada;
- si bloquea trading;
- si solo es visual.

## Regla actual

Inicialmente Torum filtra:

```text
currency = USD
impact = HIGH
country = US / United States
```

Las noticias USD de alto impacto afectan a:

```text
XAUUSD, XAUEUR, XAUAUD, XAUJPY
```

Por defecto, cada noticia crea zonas desde 60 minutos antes hasta 60 minutos despues.

## Configuracion

Endpoint:

```text
GET /api/news/settings
PATCH /api/news/settings
```

Campos principales:

```json
{
  "draw_news_zones_enabled": true,
  "block_trading_during_news": false,
  "minutes_before": 60,
  "minutes_after": 60,
  "currencies_filter": ["USD"],
  "countries_filter": ["US", "United States"],
  "impact_filter": ["HIGH"],
  "affected_symbols": ["XAUUSD", "XAUEUR", "XAUAUD", "XAUJPY"]
}
```

`block_trading_during_news=false` por defecto. Asi las zonas se pintan, pero no bloquean ordenes hasta que el usuario lo active.

## Importar JSON

```powershell
$body = Get-Content docs\examples\news_events_us_high_impact.json -Raw
Invoke-RestMethod -Method Post -ContentType "application/json" -Headers $headers -Uri http://localhost:8000/api/news/import/json -Body $body
```

## Importar CSV

Endpoint:

```text
POST /api/news/import/csv
```

Payload:

```json
{
  "source": "manual_csv",
  "csv_text": "country,currency,impact,title,event_time,previous_value,forecast_value,actual_value,source\nUnited States,USD,HIGH,Nonfarm Payrolls,2026-05-01T12:30:00Z,150K,180K,,manual_csv\n"
}
```

Columnas:

```text
country,currency,impact,title,event_time,previous_value,forecast_value,actual_value,source
```

## Zonas

Listar:

```text
GET /api/no-trade-zones?symbol=XAUUSD&from=2026-05-01T00:00:00Z&to=2026-05-02T00:00:00Z
```

Regenerar:

```text
POST /api/no-trade-zones/regenerate
```

Check:

```text
GET /api/no-trade-zones/check?symbol=XAUUSD&time=2026-05-01T12:00:00Z
```

## Grafico

El frontend pide zonas para el simbolo activo y una ventana amplia alrededor de la fecha actual. Lightweight Charts no ofrece una primitiva universal de regiones sombreadas en esta version, asi que Torum usa un overlay DOM sincronizado con `timeScale().timeToCoordinate(...)`.

La zona se pinta como:

- area sombreada;
- linea vertical de inicio;
- linea vertical de fin;
- color mas intenso cuando `blocks_trading=true`.

## Risk manager

El risk manager consulta zonas activas antes de ejecutar orden manual.

Si:

- `block_trading_during_news=true`;
- existe zona activa para el simbolo;
- la zona tiene `blocks_trading=true`;

la orden se rechaza con motivo claro.

Si el bloqueo esta desactivado, la orden no se bloquea y se devuelve un warning.

## Proveedores

Torum incluye estas interfaces:

- `BaseNewsProvider`
- `CsvNewsProvider`
- `JsonNewsProvider`
- `MyfxbookProvider`
- `FutureApiNewsProvider`

`MyfxbookProvider` queda como placeholder hasta configurar una fuente autorizada y estable. Torum no usa scraping fragil como unica via obligatoria porque el calendario economico alimenta decisiones de riesgo y bloqueo operativo.

## Futuro

- scheduler con Redis/Celery o servicio async;
- proveedor economico con contrato/licencia estable;
- alertas push PWA antes de zonas;
- configuracion por usuario/simbolo;
- zonas por divisa no USD.
