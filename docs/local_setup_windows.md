# Setup local en Windows

## Servicios Docker

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum
Copy-Item .env.example .env
docker compose up --build
```

## Frontend Vite

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum\apps\web
Copy-Item .env.example .env.local
npm install
npm run dev
```

## Verificacion

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/v1/system/status
```

Abrir:

```text
http://localhost:5173
```

## MT5 Bridge real

Con MT5 abierto y backend funcionando:

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum\services\mt5_bridge
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m bridge.main
```

Para Tailscale, cambia en `services/mt5_bridge/.env`:

```text
TORUM_API_BASE_URL=http://<ip-o-dns-tailscale>:8000
```

## Trading manual PAPER

1. Inicia sesion en la PWA.
2. Inicia `mock market data` desde la app o por API para tener ticks frescos.
3. Mantén modo `PAPER`.
4. Envia una orden desde el panel manual.
5. Revisa ordenes y posiciones en la tabla inferior.

En la UI movil, usa el panel compacto `BUY`, confirma el popup y revisa el marcador de compra y la linea de TP en el grafico.

El modo `PAPER` no necesita MT5 ni `MT5_ALLOW_ORDER_EXECUTION=true`.

## UI movil por Tailscale

Para abrir Torum desde un telefono conectado a Tailscale:

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum\apps\web
npm run dev:host
```

Configura `apps/web/.env.local` con:

```text
VITE_API_BASE_URL=http://<tailscale-host>:8000
VITE_WS_BASE_URL=ws://<tailscale-host>:8000
```

Abre `http://<tailscale-host>:5173` en el movil.

## Trading manual DEMO

Con MT5 abierto en cuenta demo, edita `services/mt5_bridge/.env`:

```text
MT5_ALLOW_ORDER_EXECUTION=true
MT5_ALLOWED_ACCOUNT_MODES=DEMO
MT5_ENABLE_REAL_TRADING=false
```

Arranca el bridge:

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum\services\mt5_bridge
.\.venv\Scripts\Activate.ps1
python -m bridge.main
```

Comprueba:

```powershell
Invoke-RestMethod http://localhost:8000/api/mt5/status
Invoke-RestMethod http://127.0.0.1:9100/health
```

Luego cambia la PWA a `DEMO`. El backend bloqueara si la cuenta detectada no es demo.

## LIVE

LIVE esta bloqueado por defecto. No cambies `MT5_ENABLE_REAL_TRADING`, `MT5_ALLOWED_ACCOUNT_MODES=REAL` ni `live_trading_enabled` sin revisar `docs/trading_manual.md`.

## Noticias y zonas de no operar

Importa eventos de ejemplo:

```powershell
$body = Get-Content docs\examples\news_events_us_high_impact.json -Raw
Invoke-RestMethod -Method Post -ContentType "application/json" -Headers $headers -Uri http://localhost:8000/api/news/import/json -Body $body
```

En la PWA, el panel "Noticias y zonas" permite:

- pintar zonas;
- activar/desactivar bloqueo;
- cambiar minutos antes/despues;
- importar JSON o CSV;
- regenerar zonas.

Por defecto las zonas se pintan, pero no bloquean operativa.
