# Tailscale

Para acceso desde otros dispositivos en la red Tailscale, backend y frontend deben escuchar en todas las interfaces.

## Backend

En `.env`:

```text
TAILSCALE_ENABLED=true
API_BIND_HOST=0.0.0.0
PUBLIC_HOST=<ip-o-dns-tailscale>
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://<ip-o-dns-tailscale>:5173
```

Arranque:

```powershell
docker compose up --build
```

## Frontend

En `apps/web/.env.local`:

```text
VITE_API_BASE_URL=http://<ip-o-dns-tailscale>:8000
VITE_WS_BASE_URL=ws://<ip-o-dns-tailscale>:8000
VITE_PUBLIC_HOST=<ip-o-dns-tailscale>
VITE_TAILSCALE_MODE=true
```

Arranque:

```powershell
npm run dev:host
```
