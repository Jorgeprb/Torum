# Mobile responsive UI

Torum usa una interfaz mobile-first para que el grafico sea la superficie principal.

## Breakpoints

- pequeno: `<= 380px`
- movil normal: `381px - 480px`
- movil grande: `481px - 767px`
- tablet: `768px - 1024px`
- desktop: `> 1024px`

## Layout movil

- Top bar negra con menu hamburguesa, selector de simbolo, selector de timeframe, alerta, lapiz de dibujos y estado del stream.
- No hay segunda barra de simbolo/timeframe/precio en movil; se elimino para recuperar altura de grafico.
- Panel BUY compacto solo con lotaje, botones `+` / `-` y `BUY`.
- El precio se ve en el eje y en las lineas dinamicas `BID`/`ASK`, no dentro del panel de compra.
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

- El lapiz abre un menu compacto de herramientas: horizontal, vertical, tendencia, rectangulo, texto y zona manual.
- El icono de alerta es toggle: activo permite tocar el grafico para crear una alerta `BELOW`; al crearla se desactiva.
- El bottom nav no es obligatorio en esta fase; la navegacion principal esta en el drawer.

## Zoom y seguimiento

Torum ya no hace `fitContent()` con cada tick. Al cargar datos iniciales, cambiar simbolo o timeframe se autoajusta el grafico. Si haces pan o zoom manual, se desactiva el seguimiento automatico y aparece el boton `Seguir precio`.

## Lineas BID/ASK

Las lineas `BID` y `ASK` son overlays dinamicos, no dibujos persistentes. Se actualizan con cada tick y se pueden activar/desactivar en Ajustes:

- `Mostrar linea BID`
- `Mostrar linea ASK`

Si hay diferencia con MT5, abre Ajustes -> Diagnostico de mercado y compara `Backend latest BID/ASK` con el simbolo exacto de MT5.
