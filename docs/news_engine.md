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
  "provider": "FINNHUB",
  "provider_enabled": true,
  "auto_sync_enabled": true,
  "sync_interval_minutes": 1440,
  "days_ahead": 14,
  "draw_news_zones_enabled": true,
  "block_trading_during_news": false,
  "minutes_before": 60,
  "minutes_after": 60,
  "last_sync_at": null,
  "last_sync_status": null,
  "last_sync_error": null,
  "currencies_filter": ["USD"],
  "countries_filter": ["US", "United States"],
  "impact_filter": ["HIGH"],
  "affected_symbols": ["XAUUSD", "XAUEUR", "XAUAUD", "XAUJPY"]
}
```

`block_trading_during_news=false` por defecto. Asi las zonas se pintan, pero no bloquean aperturas hasta que el usuario lo active. Cerrar posiciones sigue permitido aunque exista noticia activa.

## Provider automatico

Torum soporta:

- `FINNHUB`
- `MANUAL`

La opcion automatica es `FINNHUB`. Torum descarga el calendario economico, filtra localmente EEUU/USD + noticias de alto impacto y guarda solo noticias reales importadas desde el provider.

Variables:

```text
FINNHUB_CALENDAR_URL=https://finnhub.io/api/v1/calendar/economic
FINNHUB_API_KEY=
NEWS_PROVIDER_TIMEOUT_SECONDS=10
```

Endpoints:

```text
GET /api/news/providers/status
POST /api/news/providers/sync
```

El sync automatico corre al arrancar y cada `sync_interval_minutes`, si:

- `provider_enabled=true`;
- `auto_sync_enabled=true`;
- `provider` no es `MANUAL`.

El sync usa el mismo filtrado de `proba.py`:

- EEUU por `country`, `countryName`, `region` o `currency=USD`;
- alto impacto por patrones como NFP, CPI, PPI, PCE, FOMC, tipos, GDP, retail sales, ISM, JOLTS, ADP y similares;
- excluye eventos como permisos de construccion, ventas de casas y PMI final.

Luego crea o actualiza `news_events` y regenera `no_trade_zones` para:

```text
XAUUSD, XAUEUR, XAUAUD, XAUJPY
```

La deduplicacion usa primero:

```text
source + external_id
```

Si no existe `external_id`, usa fingerprint:

```text
source + currency + title + event_time
```

## Pagina Noticias

En el burger menu movil hay pagina `Noticias`.

Permite:

- elegir `FINNHUB` o `MANUAL`;
- activar provider y sync automatico;
- cambiar intervalo y dias hacia delante;
- activar bloqueo operativo;
- cambiar minutos antes/despues;
- activar o desactivar dibujado en grafico;
- sincronizar ahora;
- ver ultima sync, proxima noticia HIGH USD, errores, noticias importadas y zonas generadas.

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

Si `draw_news_zones_enabled=false`, `/api/chart/overlays` no devuelve zonas de noticias para el grafico. Las zonas siguen existiendo para risk manager y para la pagina Noticias.

## Futuro visual

Las velas siguen siendo reales. Solo nacen desde ticks guardados por Torum. No se crean candles futuras.

Las zonas futuras de noticias son overlays visuales. Para que `timeToCoordinate(...)` pueda pintar una zona que todavia no tiene velas, el grafico crea una serie invisible de padding temporal. Esa serie:

- no tiene OHLC;
- no se muestra;
- no alimenta indicadores;
- no cambia datos reales;
- solo extiende el eje temporal.

Opciones visuales locales:

```text
showFutureNewsZones=true
autoExtendToFutureNews=true
```

Estan en Ajustes:

- `Zonas futuras`;
- `Extender tiempo futuro`.

Aunque el eje se extienda, el viewport inicial se conserva. Al abrir app, cambiar activo, cambiar timeframe o pulsar centrar, Torum centra la ultima vela real, no el ultimo overlay futuro.

El usuario ve zonas futuras solo si:

- hace scroll manual hacia la derecha;
- pulsa el boton del grafico `Ver proximas noticias`.

El boton mueve el viewport a la siguiente zona futura y desactiva el auto-follow. El boton de centrar vuelve a la ultima vela real.

## Risk manager

El risk manager consulta zonas activas antes de ejecutar orden manual de apertura.

Si:

- `block_trading_during_news=true`;
- existe zona activa para el simbolo;
- la zona tiene `blocks_trading=true`;

la apertura se rechaza con motivo claro.

Si el bloqueo esta desactivado, la orden no se bloquea y se devuelve un warning.

El cierre de posiciones no pasa por este bloqueo. Una BUY abierta puede cerrarse durante noticia.

## Futuro

- scheduler avanzado con Redis/Celery si hace falta escalar;
- alertas push PWA antes de zonas;
- configuracion por usuario/simbolo;
- zonas por divisa no USD.
