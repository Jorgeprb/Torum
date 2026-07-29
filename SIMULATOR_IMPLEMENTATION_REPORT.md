# Informe de integración — Simulador histórico Torum V1

## Alcance

Se sustituyó la simulación embebida en los ajustes de estrategia por un laboratorio histórico independiente accesible desde el menú hamburguesa.

Ruta de interfaz:

```text
#/strategy/simulator
```

Endpoints principales:

```text
POST   /api/strategies/torum-v1/backtest/jobs
GET    /api/strategies/torum-v1/backtest/jobs/{job_id}
DELETE /api/strategies/torum-v1/backtest/jobs/{job_id}
```

El endpoint síncrono `POST /api/strategies/torum-v1/backtest` permanece disponible para compatibilidad.

## Funcionalidad integrada

### Navegación

- Nueva opción **Simulador** en el menú de cuenta/hamburguesa.
- Ruta independiente en `Shell`.
- Panel dedicado dentro del workspace.
- Los ajustes de Torum V1 conservan un acceso directo al laboratorio, pero ya no contienen el simulador antiguo.

### Configuración del escenario

- Activos XAUUSD y XAUEUR.
- Hasta 10.000 velas M5.
- Rango de fecha/hora opcional.
- Balance inicial.
- Perfiles Realista, Conservador y Solo técnico.
- Activación independiente de:
  - sesión;
  - desbloqueo H2/H3;
  - noticias;
  - DXY;
  - regiones Torum;
  - soportes S1/S2/S3;
  - capacidad ATH;
  - riesgo agregado.
- Selección individual, total o vacía de regiones y soportes.
- Modelo de entrada al cierre o apertura siguiente.
- Spread, slippage y comisión.
- Cierre opcional de posiciones al final.
- Niveles de traza SUMMARY, SIGNALS y FULL.
- Cola de simulaciones con progreso por fases.
- Cancelación cooperativa real en backend.
- Reanudación del seguimiento tras volver a la pantalla mediante `sessionStorage`.
- Máximo de dos simulaciones históricas ejecutándose en paralelo para proteger la API.

### Editor temporal completo

El simulador reutiliza el esquema de configuración generado desde `TorumV1Params`:

- modo esencial o avanzado;
- búsqueda por nombre, descripción o clave;
- grupos de condiciones;
- overrides temporales separados para XAUUSD y XAUEUR;
- restauración individual o completa;
- ningún cambio se publica en el bot.

### Motor histórico

Se creó `TorumV1BacktestEngine`, sin efectos secundarios. El motor:

- reutiliza `should_buy_torum_v1()`;
- carga velas M5 históricas;
- usa regiones y soportes manuales seleccionados;
- aplica sesión, noticias y DXY históricos;
- reconstruye desbloqueo H2/H3;
- aplica capacidad ATH y riesgo agregado;
- degrada multiplicadores cuando corresponde;
- simula TP, spread, slippage y comisiones;
- calcula balance, equity, drawdown, MFE y MAE;
- no crea órdenes, señales ni posiciones;
- se ejecuta dentro de un trabajo efímero aislado, sin tocar los jobs de trading.

El desbloqueo se precalcula una sola vez por jornada para evitar consultas H2/H3 por cada vela M5.

### Gráfico de simulación

- Velas M5 con zoom y desplazamiento.
- `minBarSpacing=0.5` para análisis denso.
- Regiones Torum.
- Bandas S1/S2/S3.
- Pullbacks.
- Flechas de entrada y salida.
- Línea discontinua entre entrada y salida.
- Marcadores opcionales de bloqueos.
- Coordenadas temporales interpoladas para evitar que eventos no alineados exactamente con el inicio de vela desaparezcan o se desplacen.
- Centrado desde la tabla de operaciones.
- Centrado desde cualquier evento de depuración con precio.
- Tooltip OHLC.

### Métricas

- Resultado neto.
- Balance y equity final.
- Operaciones abiertas/cerradas.
- Win rate.
- Profit factor.
- Expectativa.
- Ganancia y pérdida media.
- Mejor y peor operación.
- Drawdown máximo.
- Rachas.
- Exposición.
- Duración media.
- MFE/MAE.
- Desglose por soporte.
- Desglose por región.
- Señales detectadas y bloqueadas.
- Motivos de rechazo.
- Comparación contra la ejecución anterior.
- Curva de balance y equity.

### Depuración

- Filtro por etapa.
- Filtro por estado.
- Búsqueda textual en motivo y payload.
- Resumen clicable de motivos de rechazo.
- Inspección JSON de cada evaluación.
- Centrado del evento en el gráfico.
- Límite configurable y aviso de traza truncada.

### Exportación

- JSON completo del backtest.
- CSV de operaciones.

## Archivos principales

### Backend

- `services/api/app/strategies/torum_v1_backtest.py`
- `services/api/app/strategies/torum_v1_backtest_jobs.py`
- `services/api/app/strategies/schemas.py`
- `services/api/app/strategies/routes.py`
- `services/api/tests/test_strategy_backtest.py`

### Frontend

- `apps/web/src/features/strategies/simulator/StrategySimulatorPage.tsx`
- `apps/web/src/features/strategies/simulator/StrategySimulationChart.tsx`
- `apps/web/src/features/strategies/simulator/StrategySimulationMetrics.tsx`
- `apps/web/src/features/strategies/simulator/StrategySimulationTrades.tsx`
- `apps/web/src/features/strategies/simulator/StrategySimulationDebug.tsx`
- `apps/web/src/features/strategies/simulator/StrategyEquityChart.tsx`
- `apps/web/src/features/mobile/AccountDrawer.tsx`
- `apps/web/src/components/layout/Shell.tsx`
- `apps/web/src/features/trading/TradingWorkspacePanels.tsx`
- `apps/web/src/features/strategies/StrategyPanel.tsx`
- `apps/web/src/services/strategies.ts`
- `apps/web/src/styles.css`

### Documentación

- `docs/strategy_simulator.md`
- `docs/strategy_workbench.md`
- `README.md`

## Validaciones realizadas

```text
Python compileall: correcto
Pruebas específicas estrategia/simulador: 74 superadas
TypeScript tsc --noEmit: correcto
git diff --check: correcto
```

La suite backend completa no pudo ejecutarse en el entorno de revisión porque `passlib` no está instalado y el repositorio de paquetes disponible no lo ofreció. Las pruebas específicas del motor y del workbench sí se ejecutaron.

El build Vite no pudo completarse con el `node_modules` incluido en el ZIP porque procede de otra plataforma y no contiene `@rollup/rollup-linux-x64-gnu`. `npm run typecheck` sí finalizó correctamente. Una instalación limpia con `npm ci` en el equipo de despliegue debe instalar el binario opcional correspondiente.

## Limitaciones del modelo histórico

- Una vela M5 no aporta la hora intravela exacta del TP.
- No se puede resolver el orden de varios eventos dentro de la misma vela sin ticks históricos.
- El resultado depende de la cobertura histórica de DXY, noticias y velas.
- Regiones y soportes respetan sus coordenadas temporales reales.
- El cálculo monetario usa la configuración de `contract_size` y conversión de riesgo almacenada, no el motor nativo de profit del broker.

No se añadió ninguna migración de base de datos para esta funcionalidad.
