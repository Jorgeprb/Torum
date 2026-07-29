# Torum — fluidez, exactitud MT5 y robustez

## Alcance

Esta revisión aplica las mejoras de todas las fases solicitadas sobre el proyecto actualizado: exactitud del historial, reconciliación con MetaTrader 5, latencia de compra/cierre, drawings, gráfico vivo, flechas de ejecución, zoom, pullbacks, polling, seguridad y observabilidad.

La arquitectura base endurecida se mantiene: acceso MT5 serializado y priorizado, envío de ticks desacoplado, trabajos durables, snapshots de riesgo, autenticación interna y estrategia disparada por cierre M5.

## 1. MT5 como fuente de verdad

### Posiciones abiertas

`PositionService.sync_mt5_positions()` sustituye los datos provisionales de Torum por los oficiales de `positions_get()`:

- precio de apertura;
- hora de apertura y `time_msc`;
- volumen y lado;
- precio actual;
- SL/TP;
- profit flotante oficial;
- cuenta, servidor y ticket.

La sincronización devuelve las posiciones modificadas como payload incremental. El WebSocket las actualiza localmente sin provocar un refresco completo cada 500 ms.

### Posiciones cerradas

Los deals se agregan por `position_id` y se reconstruyen con:

- precio de entrada medio ponderado;
- precio de salida medio ponderado;
- hora exacta de entrada y salida en milisegundos;
- profit, swap, comisión y fee;
- neto oficial = profit + swap + comisión + fee.

Un deal sin `entry` ya no se interpreta como cierre. Una posición cerrada provisionalmente permanece con `enrichment_status=PENDING_MT5_DEAL` hasta que el broker confirma los deals.

### Reconciliación

- una ausencia aislada no cierra una posición;
- el cierre por ausencia exige confirmaciones consecutivas y encola enriquecimiento oficial;
- al arrancar se ejecuta una reconciliación histórica amplia una sola vez;
- después se usa cursor incremental de deals;
- las asociaciones usan cuenta, servidor, ticket y una ventana temporal estrecha.

## 2. Compra y cierre

### Compra

El camino crítico queda reducido a:

```text
UI → API → bridge prioritario → MT5 order_send → persistencia mínima → respuesta
```

Mejoras:

- se elimina un commit intermedio antes de `order_send`;
- el bridge devuelve una instantánea de la posición recién creada si MT5 no devuelve directamente ticket/precio;
- se evita una consulta HTTP adicional al bridge cuando esa instantánea ya está disponible;
- la UI muestra un marcador temporal «Enviando…» al confirmar, lo sustituye por la posición oficial y pinta BUY/TP sin esperar polling;
- TP, riesgo, notificaciones y reconciliación posterior siguen siendo trabajos durables e idempotentes;
- el bridge conserva caché de símbolo seleccionado, `symbol_info` y filling mode válido;
- las órdenes tienen prioridad sobre histórico, posiciones y mercado.

### Cierre

- el popup se cierra inmediatamente;
- la posición desaparece de abiertas de forma optimista;
- si MT5 falla, se restaura;
- el request de cierre no espera a recorrer todo el histórico;
- el deal oficial se enriquece después mediante trabajo durable;
- el frontend recibe eventos incrementales `position_closed`/`position_updated` con la posición concreta;
- se elimina la necesidad de refrescar órdenes, abiertas e historial completos por cada sync.

La parte que siga tardando dentro de `order_send` depende del terminal, red y broker.

## 3. Gráfico vivo y fluidez

### Ticks y vela actual

- los ticks se agrupan a 20 Hz para evitar un render React por tick;
- el contador de ticks actualiza una vez por segundo;
- la vela viva se actualiza con `series.update()`;
- `series.setData()` queda reservado para carga/reset/cambio de mercado/histórico;
- no se reescriben miles de velas en IndexedDB en cada tick;
- IndexedDB migra a almacenamiento por bloques temporales de 256 velas y solo reescribe los bloques modificados;
- las escrituras se agrupan con debounce;
- BID/ASK se actualizan imperativamente y no se eliminan al cambiar solo timeframe.

### Overlays

- los recalculados se agrupan con `requestAnimationFrame`;
- múltiples eventos de zoom, pan, tick o drag en el mismo frame producen un solo cálculo;
- el modo denso elimina glow y etiquetas secundarias para mejorar FPS;
- los drawings no fuerzan una recarga general de overlays.

### Polling

- WebSocket es la fuente principal;
- trading se reconcilia cada 15 s como recuperación;
- estado MT5 cada 10 s;
- ajustes cada 30 s;
- eventos de posiciones actualizan el elemento concreto;
- la sincronización MT5 ya no provoca `refreshTradingData()` completo cada 0,5 s.

## 4. Drawings

- creación optimista con ID temporal;
- actualización optimista;
- eliminación optimista con rollback;
- persistencia al soltar, no durante cada `pointermove`;
- secuencias de petición para ignorar respuestas antiguas;
- campo `revision` y rechazo 409 de mutaciones obsoletas;
- solo se invalida PB/contexto de estrategia si el drawing afecta a soportes o zonas.

## 5. Flechas de entrada/salida

- identidad canónica por cuenta + servidor + ticket MT5;
- deduplicación de posiciones e historial;
- prioridad de datos oficiales sobre provisionales;
- X anclada a la vela que contiene el timestamp;
- Y en el precio exacto MT5;
- tooltip conserva la hora exacta en milisegundos;
- no se extrapolan flechas fuera del histórico cargado;
- entrada y salida en la misma vela usan solo un pequeño offset visual en píxeles;
- recargar la aplicación no modifica la vela de anclaje.

Además, el historial limita la carga incremental a 100 filas y usa `content-visibility`/containment CSS para que el navegador no maquete ni pinte filas fuera del viewport.

## 6. Zoom y densidad

Nuevo ajuste de densidad:

```text
WIDE     barSpacing 14, min 2
NORMAL   barSpacing 9,  min 1
COMPACT  barSpacing 5,  min 0.75
ULTRA    barSpacing 2.5,min 0.5
```

Máximo visible ampliado:

```text
M1 800 · M5 500 · M15 400 · H1 300 · H2 280 · H3 260 · H4 250 · D1 220 · W1 160
```

Cuando las barras son muy finas se simplifican adornos no esenciales para conservar fluidez.

## 7. Pullbacks

Se añade endpoint específico y caché:

```http
GET /api/strategies/torum-v1/pullbacks
```

Características:

- clave por usuario, símbolo, última vela M5 y hash de parámetros;
- ventana limitada, por defecto 600 velas;
- invalidación al cambiar configuración;
- el botón PB pinta el último snapshot en memoria inmediatamente;
- refresco en background sin cargar noticias, drawings, posiciones ni todos los overlays;
- PB cerrados se recalculan al cerrar M5 o cambiar parámetros;
- solo el PB vivo se ajusta localmente con ticks.

## 8. Seguridad y aislamiento

- trader solo ve sus posiciones, órdenes e historial;
- admin mantiene visión global;
- cierre y cambio de TP comprueban propiedad;
- reconciliación MT5 es administrativa/interna;
- endpoints bridge/API internos siguen protegidos con token de servicio.

## 9. Base de datos

Nueva migración:

```text
0021_fluency_and_mt5_truth
```

Añade:

- `positions.open_time_msc`;
- `positions.close_time_msc`;
- `positions.enrichment_status`;
- `chart_drawings.revision`;
- índices de cuenta/ticket/estado, símbolo/estado/hora, drawings, candles DESC y ticket de orden.

Aplicación:

```bash
docker compose up -d timescaledb redis
docker compose run --rm api alembic upgrade head
```

## 10. Configuración recomendada

Bridge:

```env
MT5_POSITION_SYNC_INTERVAL_SECONDS=0.5
MT5_DEALS_SYNC_INTERVAL_SECONDS=5
MT5_DEALS_HISTORY_LOOKBACK_DAYS=365
MT5_STARTUP_HISTORY_RECONCILE_ENABLED=true
MT5_STARTUP_HISTORY_RECONCILE_DELAY_SECONDS=5
```

El histórico de 365 días se consulta una vez al arrancar; la operación normal es incremental.

## 11. Validación realizada

```text
Python compileall: correcto
Pytest: 204 passed
TypeScript tsc --noEmit: correcto
git diff --check: correcto
```

El entorno de ejecución no contiene la dependencia opcional nativa Linux de Rollup (`@rollup/rollup-linux-x64-gnu`) dentro del `node_modules` aportado. Por eso no fue posible completar `vite build` aquí, aunque TypeScript sí compila sin errores. El ZIP final no incluye `node_modules`; al ejecutar `npm ci` en el equipo de destino se instalará el binario correcto para su plataforma.

Las pruebas Python necesitaron un stub únicamente de test para `passlib`, porque ese paquete no está instalado en este entorno. El stub está fuera del proyecto y no se incluye en la entrega.

No se ejecutó una orden real contra MetaTrader 5 desde este entorno. La latencia y los datos oficiales deben verificarse finalmente en MetaQuotes-Demo.

## 12. Prueba final recomendada

1. Aplicar migraciones.
2. Ejecutar `npm ci` y `npm run build` en el entorno destino.
3. Arrancar MT5 Demo, bridge y API.
4. Abrir una orden mínima y comprobar:
   - respuesta inmediata tras `order_send`;
   - línea BUY inmediata;
   - TP pendiente y posterior `UPDATED`;
   - precio/hora de entrada sustituidos por MT5.
5. Cerrar y comprobar:
   - desaparición optimista;
   - deal oficial posterior;
   - precio, hora, profit, swap, comisión, fee y neto iguales a MT5.
6. Reiniciar la app y confirmar que las flechas permanecen en la misma vela.
7. Probar densidad ULTRA, drag/delete de drawings y PB desde caché.
