# Torum — informe de estabilización consolidado

Esta entrega incluye dos capas de trabajo:

1. endurecimiento estructural y de seguridad (`0020_reliability_hardening`);
2. fluidez y fuente de verdad MT5 (`0021_fluency_and_mt5_truth`).

El detalle completo de la segunda capa está en:

```text
PERFORMANCE_AND_MT5_TRUTH_REPORT.md
```

## Correcciones estructurales

- acceso MT5 serializado mediante coordinador con prioridad para abrir, cerrar y aplicar TP;
- recogida y envío de ticks desacoplados mediante cola;
- sincronización incremental de deals con cursor;
- reconciliación segura de posiciones;
- identidad canónica por cuenta, servidor y ticket;
- TP y enriquecimiento de cierres mediante trabajos durables, idempotentes y reintentables;
- snapshot de riesgo persistente y aislado por cuenta;
- estrategia Torum ejecutada al cierre M5, no por cada batch de ticks;
- endpoints internos protegidos con token de servicio;
- WebSocket autenticado y broadcast concurrente;
- índice de ticks con `time_msc`, compresión y retención Timescale;
- correlation ID y tiempos de operación;
- secretos retirados del código;
- API restringida a un worker mientras los coordinadores sean process-local.

## Correcciones de fluidez y exactitud

- precios, horas y profit de MT5 sobrescriben datos provisionales;
- historial reconstruido con deals, incluyendo fee y neto;
- compra/cierre actualizan UI de forma optimista e incremental;
- sync MT5 emite la posición concreta y no fuerza refrescos completos cada 500 ms;
- vela viva con `series.update()` y ticks agrupados;
- drawings optimistas y versionados;
- flechas ancladas a la vela correcta con timestamps MT5;
- zoom hasta `minBarSpacing=0.5` en modo ULTRA;
- pullbacks con endpoint y caché específicos;
- polling reducido y WebSocket como fuente principal;
- trader aislado a sus propias órdenes/posiciones/historial.

## Migraciones

Antes de arrancar:

```bash
docker compose up -d timescaledb redis
docker compose run --rm api alembic upgrade head
```

La cabeza actual es:

```text
0021_fluency_and_mt5_truth
```

## Configuración

Copiar ejemplos y generar secretos nuevos:

```bash
cp .env.example .env
cp services/mt5_bridge/.env.example services/mt5_bridge/.env
```

Configurar el mismo `TORUM_SERVICE_TOKEN` en API y bridge.

## Validación

```text
Python compileall: correcto
Pytest: 204 passed
TypeScript typecheck: correcto
git diff --check: correcto
```

`vite build` no pudo completarse en este contenedor porque el `node_modules` aportado no incluye el binario opcional de Rollup para Linux. Debe ejecutarse `npm ci` en el equipo destino. No se realizó una orden real contra MT5 desde este entorno.

## Límites externos

- la latencia dentro de `MT5.order_send` depende del terminal, red y broker;
- Android/iOS pueden congelar una PWA en segundo plano; Torum mantiene conexión cuando es posible y fuerza reconexión/resincronización al volver, pero el sistema operativo no garantiza un WebSocket permanente.
