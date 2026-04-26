# Mobile responsive UI

Torum usa una interfaz mobile-first para que el grafico sea la superficie principal.

## Breakpoints

- pequeno: `<= 380px`
- movil normal: `381px - 480px`
- movil grande: `481px - 767px`
- tablet: `768px - 1024px`
- desktop: `> 1024px`

## Layout movil

- Top bar negra con menu hamburguesa, accesos de dibujo/alerta, timeframe y estado del stream.
- Selector compacto de simbolo/timeframe.
- Panel BUY compacto con precio, lote calculado y botones `+` / `-`.
- Grafico Lightweight Charts ocupando casi todo el viewport.
- Drawer lateral para cuenta, grafico, estrategias, indicadores y ajustes.

Se usa `100dvh` y `safe-area-inset` para PWA movil, evitando que barras del navegador tapen el grafico.

## Drawer

El drawer muestra:

- login/servidor si MT5 lo reporta;
- modo `DEMO` / `REAL` / `UNKNOWN`;
- balance, equity y margen libre;
- estado MT5/backend/fuente de mercado;
- navegacion a Grafico, Estrategias, Indicadores y Ajustes.

## Tailscale

Levanta backend y frontend escuchando en todas las interfaces:

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum
docker compose up -d --build api

cd apps\web
npm run dev:host
```

En `apps/web/.env.local` usa tu host Tailscale:

```text
VITE_API_BASE_URL=http://<tailscale-host>:8000
VITE_WS_BASE_URL=ws://<tailscale-host>:8000
```

Abre desde el movil:

```text
http://<tailscale-host>:5173
```

## PWA

Desde el navegador movil, instala Torum como app. El layout esta pensado para uso vertical, aunque tablet horizontal tambien queda soportado.

## Limitaciones actuales

- Los dibujos moviles tienen accesos rapidos; la edicion avanzada sigue en panel.
- El bottom nav no es obligatorio en esta fase; la navegacion principal esta en el drawer.
- Las alertas tienen acceso visual preparado, pero las alertas push reales pertenecen a la fase de alertas.
