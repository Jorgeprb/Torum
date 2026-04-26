# Chart Overlays

`GET /api/chart/overlays` es el endpoint comun para pintar capas sobre el grafico.

```text
GET /api/chart/overlays?symbol=XAUUSD&timeframe=H1
```

Respuesta:

```json
{
  "symbol": "XAUUSD",
  "timeframe": "H1",
  "indicators": [],
  "no_trade_zones": [],
  "drawings": []
}
```

## Fuentes

- `indicators`: overlays calculados desde velas de Torum.
- `no_trade_zones`: zonas derivadas de noticias.
- `drawings`: dibujos persistentes visibles del usuario autenticado.

## Separacion conceptual

No todo overlay es un dibujo persistente:

- un indicador se recalcula;
- una zona de noticias se genera desde `news_events`;
- un dibujo manual se guarda en `chart_drawings`;
- una futura estrategia podra producir markers o zonas no persistentes.

Esta separacion evita mezclar configuracion manual con resultados calculados.

## Autenticacion

El endpoint sigue devolviendo indicadores y zonas de noticias sin usuario. Si recibe un token valido, agrega dibujos visibles de ese usuario.
