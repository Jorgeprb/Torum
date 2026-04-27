# Reconexion y resync

En movil y en PWA es normal que el navegador suspenda WebSockets cuando la app queda en segundo plano. Torum no exige refrescar manualmente: al volver a primer plano reconstruye el socket y resincroniza estado critico por REST.

## Estados

El indicador superior usa el WebSocket manager centralizado:

- `connecting`: abriendo conexion.
- `connected`: socket abierto y datos recientes.
- `reconnecting`: socket cerrado o sospechoso; reintentando con backoff.
- `stale`: el socket parece abierto, pero no llegaron mensajes/heartbeat a tiempo.
- `disconnected`: sin conexion activa.

## Heartbeat

El frontend envia periodicamente:

```json
{ "type": "ping", "ts": 1770000000000 }
```

El backend responde:

```json
{ "type": "pong", "ts": 1770000000000, "server_time": "..." }
```

Si no llega ningun mensaje durante el umbral de stale, Torum cierra el socket viejo y abre uno nuevo. Antes de abrir un socket nuevo, elimina handlers del anterior para evitar conexiones duplicadas.

## Primer plano y red

Torum escucha:

- `visibilitychange`
- `focus`
- `online`
- `offline`
- `pageshow`

Al volver a visible/focus/online ejecuta `resyncAfterReconnect()`:

- velas recientes;
- ultimo tick BID/ASK;
- posiciones abiertas y cerradas recientes;
- ordenes;
- estado MT5/bridge;
- ajustes de trading;
- alertas activas;
- dibujos y overlays.

## Trading con datos stale

En `DEMO` y `LIVE`, Torum bloquea compras, cierre de posiciones y modificacion de TP si el stream esta `stale`, `reconnecting` o `disconnected`.

Mensaje esperado:

```text
Datos desconectados o desactualizados. Reconectando...
```

`PAPER` puede seguir siendo mas permisivo, pero el estado visual seguira indicando que el mercado no esta fresco.

## Service worker

La PWA no cachea rutas dinamicas de trading/mercado:

- `/api/market`
- `/api/candles`
- `/api/ticks`
- `/api/positions`
- `/api/orders`
- `/api/mt5`
- `/api/trade-history`
- `/api/alerts`

El cache queda para assets estaticos. WebSocket no se cachea.

## Comprobacion manual

1. Abre Torum en Chrome o como PWA.
2. Comprueba que el indicador superior esta conectado.
3. Manda la app a segundo plano 30-60 segundos.
4. Vuelve a abrirla.
5. Debe aparecer `Reconectando` si el socket fue suspendido y luego `Stream conectado`.
6. Revisa Ajustes -> Diagnostico de mercado: `Frontend latest` y `Backend latest` deben actualizarse.
7. En DevTools Network -> WS no deberian acumularse sockets viejos vivos para el mismo simbolo/timeframe.
