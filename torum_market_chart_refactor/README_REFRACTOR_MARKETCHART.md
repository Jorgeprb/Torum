# Refactor de `MarketChart.tsx` para Torum

Este paquete divide parte del `MarketChart.tsx` en módulos pequeños y coherentes.

> Importante: no he podido clonar el repo desde el contenedor por DNS, así que este paquete está preparado como refactor por fases. La fase 1 es segura porque extrae helpers puros, tipos y utilidades sin cambiar la arquitectura del componente.

## Qué incluye

Copia estas carpetas/archivos en la raíz de tu repo Torum:

```text
apps/web/src/features/chart/chartTypes.ts
apps/web/src/features/chart/chartTime.ts
apps/web/src/features/chart/chartData.ts
apps/web/src/features/chart/chartStyle.ts
apps/web/src/features/chart/chartCoordinates.ts
apps/web/src/features/chart/chartView.ts
apps/web/src/features/chart/tradeLineLabel.ts
apps/web/src/features/chart/useLightweightChart.ts
apps/web/src/features/chart/alerts/alertVisualStyles.ts
apps/web/src/features/chart/drawings/torumZones.ts
apps/web/src/features/chart/drawings/drawingGeometry.ts
apps/web/src/features/chart/drawings/drawingHitTesting.ts
apps/web/src/features/chart/drawings/DrawingHtmlLayer.tsx
scripts/apply_market_chart_phase1.py
```

## Aplicación automática de la fase 1

Desde la raíz del repo:

```bash
python scripts/apply_market_chart_phase1.py
```

El script crea backup:

```text
apps/web/src/features/chart/MarketChart.tsx.before-refactor-phase1
```

y modifica `MarketChart.tsx` para:

- importar tipos desde `chartTypes.ts`
- importar helpers de tiempo desde `chartTime.ts`
- importar helpers de velas desde `chartData.ts`
- importar helpers de vista desde `chartView.ts`
- importar helpers de coordenadas desde `chartCoordinates.ts`
- importar estilos desde `chartStyle.ts`
- importar persistencia de estilos de alertas desde `alerts/alertVisualStyles.ts`
- importar utilidades de zonas Torum desde `drawings/torumZones.ts`
- importar geometría de dibujos desde `drawings/drawingGeometry.ts`

Después ejecuta:

```bash
cd apps/web
pnpm typecheck
pnpm build
```

Si tu proyecto no tiene `typecheck`, usa:

```bash
pnpm build
```

## Qué NO hace automáticamente todavía

No sustituye automáticamente el render de handles por `DrawingHtmlLayer.tsx`, porque esa parte depende de la versión exacta de tu `renderDrawingHtmlHandles`, `startHtmlDrawingDrag` y los cambios recientes que hiciste para long press.

Pero ya te dejo el componente preparado. Cuando quieras aplicarlo, en `MarketChart.tsx` cambia tu `renderDrawingHitLayer()` por:

```tsx
function renderDrawingHitLayer() {
  return (
    <DrawingHtmlLayer
      drawingShapes={drawingShapes}
      selectedDrawingId={effectiveSelectedDrawingId}
      onStartDrag={startHtmlDrawingDrag}
    />
  );
}
```

Y añade:

```tsx
import { DrawingHtmlLayer } from "./drawings/DrawingHtmlLayer";
```

Esto además arregla la capa HTML para que no bloquee el pan de Lightweight Charts, porque `DrawingHtmlLayer` usa `pointerEvents: "none"` en la capa y `pointerEvents: "auto"` solo en los handles.

## Orden recomendado

1. Copia los archivos.
2. Ejecuta `python scripts/apply_market_chart_phase1.py`.
3. Ejecuta build/typecheck.
4. Si todo compila, sustituye `renderDrawingHitLayer()` por `DrawingHtmlLayer`.
5. Más adelante extrae overlays visuales: `TradeLinesOverlay`, `PriceAlertsOverlay`, `PullbackDebugOverlay`, etc.

## Por qué esta división tiene sentido

- `chartTypes.ts`: contratos del componente y overlays.
- `chartTime.ts`: conversión UTC/broker/local y formatters.
- `chartData.ts`: normalización de velas y series.
- `chartView.ts`: zoom, escala, centrado, padding futuro y zonas de noticias.
- `chartCoordinates.ts`: conversión pixel/tiempo.
- `chartStyle.ts`: colores, opacidad, line styles y clamps.
- `alerts/alertVisualStyles.ts`: estilos persistidos de alertas.
- `drawings/*`: lógica de dibujos separada de la gráfica.
