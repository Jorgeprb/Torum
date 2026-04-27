# Alertas de precio

Fase 9 implementa alertas de precio persistentes y notificaciones push PWA.

## Regla unica

Todas las alertas son `BELOW`.

```text
trigger cuando current_price <= target_price
```

No existe `ABOVE` en esta fase. Si el frontend o un cliente API manda `condition_type=ABOVE`, el backend responde `422`.

## Precio usado

El evaluador usa ticks crudos de Torum:

1. `bid` si existe;
2. `last` si no hay bid;
3. `ask` como ultimo fallback.

No se usan velas de MT5.

Las alertas no dependen de timeframe. Si creas una alerta en H1, se sigue viendo y evaluando al cambiar a H4, D1 o cualquier otra temporalidad del mismo simbolo.

## Crear alerta en el grafico

1. Abre un grafico, por ejemplo `XAUUSD H4`.
2. Pulsa el icono de alerta. El boton queda activo.
3. Toca/clica el precio donde quieres crearla.
4. Torum guarda una alerta `BELOW`.
5. La linea aparece como `ALERTA <= precio`.

En movil se usan eventos `pointer`, asi que funciona con tactil. Si vuelves a pulsar el icono antes de tocar el grafico, el modo alerta se desactiva y el grafico vuelve a pan/zoom normal.

## Arrastrar alerta

Arrastra la linea horizontal hacia arriba/abajo. Al soltar:

- Torum recalcula el precio desde la escala del grafico;
- llama `PATCH /api/alerts/price/{id}`;
- guarda `target_price`;
- actualiza la etiqueta.

La persistencia guarda `target_price`, nunca pixeles.

## Disparo

Cuando entra un tick y `price <= target_price`:

- `status` pasa a `TRIGGERED`;
- se guarda `triggered_at`;
- se guarda `triggered_price`;
- se emite WebSocket `price_alert_triggered`;
- se envia push PWA si el usuario tiene suscripcion activa;
- la linea desaparece del grafico;
- no vuelve a dispararse.

## Probar con mock market

```powershell
$body = @{ username = "admin"; password = "<password>" } | ConvertTo-Json
$login = Invoke-RestMethod -Method Post -ContentType "application/json" -Uri http://localhost:8000/api/v1/auth/login -Body $body
$headers = @{ Authorization = "Bearer $($login.access_token)" }

$alert = @{
  internal_symbol = "XAUUSD"
  timeframe = $null
  target_price = 999999
  message = "Smoke BELOW"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -ContentType "application/json" -Headers $headers -Uri http://localhost:8000/api/alerts/price -Body $alert

Invoke-RestMethod -Method Post -Headers $headers http://localhost:8000/api/mock-market/start
Start-Sleep -Seconds 2
Invoke-RestMethod -Method Post -Headers $headers http://localhost:8000/api/mock-market/stop

Invoke-RestMethod -Headers $headers "http://localhost:8000/api/alerts/price/history?symbol=XAUUSD"
```

## Probar con MT5 real

Con `mt5_bridge` enviando ticks, crea una alerta por debajo del precio actual y espera a que el mercado toque el nivel. El trigger se evalua en backend cuando llega `/api/ticks/batch`.

## Tailscale/Tailgate

Esta fase no cambia configuracion de red, hosts, Docker, Tailscale ni Tailgate. La misma URL que ya usas para abrir Torum sigue siendo valida.

Para push, el navegador exige contexto seguro: `localhost` o HTTPS. Si accedes por una URL HTTPS de Tailscale/Tailgate, push puede funcionar. Si accedes por HTTP remoto, el navegador puede bloquear permisos de notificaciones.
