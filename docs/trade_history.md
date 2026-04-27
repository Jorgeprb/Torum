# Historial de operaciones

El burger menu incluye `Historial`.

La pantalla consume:

```text
GET /api/trade-history
GET /api/trade-history/{id}
```

Campos principales:

- apertura y cierre;
- simbolo;
- BUY;
- volumen;
- precio de entrada;
- precio de cierre si existe;
- TP;
- beneficio/perdida;
- modo `PAPER/DEMO/LIVE`;
- ticket MT5;
- estado.

Filtros soportados por API:

```text
symbol
mode
status
from
to
limit
```

Ejemplo:

```powershell
Invoke-RestMethod -Headers $headers "http://localhost:8000/api/trade-history?symbol=XAUUSD&status=CLOSED"
```

El historial se alimenta de `positions`. Las posiciones sincronizadas desde MT5 tambien aparecen cuando el bridge detecta apertura/cierre.

Para cierres hechos fuera de Torum, el bridge usa `history_deals_get()` y el backend guarda `close_price`, `closing_deal_ticket`, `swap` y `commission` cuando MT5 entrega esos campos.
