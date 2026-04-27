# PWA push notifications

Torum usa Web Push con VAPID. Las claves no se guardan en el codigo.

## Variables

```text
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=mailto:admin@torum.dev
```

## Generar claves VAPID

Desde el repo, usando el contenedor API:

```powershell
docker compose run --rm api python -c "from py_vapid import Vapid; import base64; v=Vapid(); v.generate_keys(); n=v.public_key.public_numbers(); pub=base64.urlsafe_b64encode(bytes([4])+n.x.to_bytes(32,'big')+n.y.to_bytes(32,'big')).rstrip(b'=').decode(); priv=base64.urlsafe_b64encode(v.private_key.private_numbers().private_value.to_bytes(32,'big')).rstrip(b'=').decode(); print('VAPID_PUBLIC_KEY='+pub); print('VAPID_PRIVATE_KEY='+priv)"
```

Copia los valores a `.env` y reinicia `api`.

## Activar en la PWA

1. Abre Torum.
2. Menu hamburguesa.
3. Ajustes.
4. Seccion `Notificaciones push`.
5. Pulsa `Activar push`.
6. Acepta el permiso del navegador.
7. Pulsa `Enviar prueba`.

## Endpoints

```text
GET    /api/push/vapid-public-key
POST   /api/push/subscribe
GET    /api/push/subscriptions
DELETE /api/push/subscribe/{id}
POST   /api/push/test
```

## Service worker

En desarrollo, Torum registra `/sw.js` al activar push.

En build PWA, `vite-plugin-pwa` genera el service worker y carga `/push-sw.js` para manejar:

- `push`;
- `notificationclick`.

Al tocar una notificacion, intenta enfocar la PWA y abrir el grafico del simbolo.

## Contexto seguro

Los navegadores requieren:

- `localhost`, o
- HTTPS.

No se cambia Tailscale/Tailgate. Si tu URL actual ya es HTTPS, usa esa. Si es HTTP remoto, puede que el navegador no permita push aunque la app cargue bien.

## Problemas comunes

- `missing-vapid`: faltan `VAPID_PUBLIC_KEY` o `VAPID_PRIVATE_KEY` en backend.
- `denied`: el navegador bloqueo permisos; hay que reactivarlos en ajustes del sitio.
- `unsupported`: el navegador o contexto no soporta Web Push.
- No llega prueba: revisa HTTPS/local, permisos, service worker y `/api/push/subscriptions`.
