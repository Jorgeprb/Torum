# Simulador histórico Torum V1

El simulador se abre desde el menú hamburguesa en **Simulador** (`#/strategy/simulator`). Se ha separado de la pantalla de ajustes para que la configuración publicada y las pruebas históricas no se mezclen.

## Cómo abrir y lanzar una simulación

1. Abre el menú hamburguesa y entra en **Simulador**. No es necesario activar ningún modo en Ajustes.
2. Configura el escenario en los cuatro pasos de la columna izquierda: **Mercado**, **Condiciones**, **Parámetros** y **Ejecución**.
3. Revisa la tarjeta **Escenario listo para probar**. Los errores bloquean el lanzamiento; los avisos explican configuraciones que pueden producir cero entradas o resultados demasiado optimistas.
4. Pulsa **Ejecutar simulación**. La pantalla muestra cola, fase y porcentaje, permite cancelar y recupera el seguimiento al volver.
5. Analiza el resultado en **Gráfico y métricas**, **Operaciones**, **Depuración** y **Cobertura**.

La pantalla guarda localmente el borrador del escenario, incluidos los overrides temporales y la selección individual de regiones y soportes para cada activo. El botón **Restaurar escenario** vuelve a los valores recomendados sin modificar la configuración publicada.

## Seguridad

La simulación es de solo lectura:

- no crea señales persistentes;
- no crea órdenes ni posiciones;
- no llama a `order_send`;
- no modifica MetaTrader 5;
- no modifica la configuración publicada;
- los cambios de parámetros son temporales y se incluyen únicamente en la petición de backtest.

## Escenario configurable

El usuario puede seleccionar:

- XAUUSD o XAUEUR;
- hasta 10.000 velas M5;
- rango de fechas opcional;
- balance inicial;
- horario y desbloqueo H2/H3;
- zonas históricas de noticias;
- filtro DXY diario con SMA;
- capacidad por ATH;
- riesgo agregado;
- regiones de operativa Torum concretas;
- soportes S1, S2 y S3 concretos;
- entrada al cierre de confirmación o en la apertura siguiente;
- spread, slippage y comisión;
- cierre forzado o mantenimiento de posiciones abiertas al final;
- nivel y límite de la traza de depuración;
- progreso por fases, cancelación cooperativa y recuperación de una simulación en curso.

El editor **Todas las condiciones de la estrategia** reutiliza el esquema de `TorumV1Params`. Permite cambiar temporalmente cualquier parámetro sin publicar ni alterar el bot activo.

## Motor histórico

La interfaz usa una cola de trabajos con progreso y cancelación real:

```text
POST   /api/strategies/torum-v1/backtest/jobs
GET    /api/strategies/torum-v1/backtest/jobs/{job_id}
DELETE /api/strategies/torum-v1/backtest/jobs/{job_id}
```

El endpoint síncrono `POST /api/strategies/torum-v1/backtest` se conserva para compatibilidad y pruebas automatizadas. El navegador guarda el identificador del trabajo en `sessionStorage`, por lo que puede reanudar la visualización del progreso tras volver a la pantalla mientras el proceso API siga activo.

El motor reutiliza `should_buy_torum_v1()` para mantener el setup técnico alineado con producción. Reconstruye alrededor de ese setup:

1. sesión;
2. desbloqueo H2/H3;
3. pullback y confirmación M5;
4. pertenencia del mínimo a una región Torum;
5. soporte y multiplicador;
6. noticias;
7. DXY histórico;
8. zona ATH y capacidad;
9. riesgo agregado;
10. ejecución simulada y TP.

El desbloqueo se precalcula una vez por jornada para evitar varias consultas H2/H3 por cada vela M5.

## Resultados

### Gráfico

Muestra:

- velas M5;
- pullbacks;
- regiones seleccionadas;
- bandas S1/S2/S3;
- flecha de entrada;
- flecha de salida;
- línea discontinua de cada transacción;
- bloqueos opcionales;
- centrado desde la tabla de operaciones o la traza de depuración.

### Métricas

Incluye:

- balance y equity final;
- resultado neto;
- win rate;
- profit factor;
- expectativa;
- drawdown máximo absoluto y porcentual;
- exposición;
- MFE y MAE;
- rachas;
- desglose por soporte;
- desglose por región;
- señales detectadas y bloqueadas;
- motivos de descarte.

### Depuración

La traza puede filtrarse por:

- etapa;
- estado;
- código de motivo;
- texto o contenido del detalle.

Cada evento con precio puede centrarse en el gráfico. El modo `FULL` conserva hasta el límite configurado y debe reservarse para ventanas de análisis reducidas.

### Exportación

- JSON completo del backtest;
- CSV de operaciones.

## Modelos de ejecución

### `NEXT_OPEN`

Es el modo recomendado. La señal se confirma al cierre y la entrada se ejecuta en la apertura de la vela siguiente, añadiendo spread y slippage.

### `CONFIRMATION_CLOSE`

Es idealizado y sirve para estudiar el setup. No representa una garantía de ejecución real en ese cierre.

## Limitaciones conocidas y explícitas

- El histórico M5 no contiene el instante intravela exacto en que se tocó un TP. La salida se ancla al inicio de la vela que contiene el toque.
- El orden entre TP y otros eventos dentro de una misma vela no puede reconstruirse sin ticks históricos.
- El resultado depende de la calidad y cobertura de las velas, DXY y zonas de noticias almacenadas.
- Las regiones y soportes usan sus coordenadas temporales reales. Un dibujo creado posteriormente no se proyecta automáticamente sobre fechas anteriores fuera de su intervalo.
- El profit usa `contract_size` y `risk_conversion_rate` configurados para el símbolo; no sustituye un backtest con ticks y cálculo nativo del broker.

## Pruebas

Las simulaciones largas se ejecutan fuera del request HTTP principal. El motor informa las fases `PREPARING`, `LOADING_MARKET`, `LOADING_CONTEXT`, `PRECOMPUTING`, `SIMULATING` y `FINALIZING`. La cancelación se comprueba de forma cooperativa durante el recorrido de velas, por lo que no queda un cálculo largo ejecutándose después de pulsar **Cancelar**.

Las pruebas de backend verifican:

- ausencia de efectos secundarios;
- generación de métricas;
- selección exacta de regiones y soportes;
- posibilidad de seleccionar ninguna región o soporte;
- conservación de los endpoints de configuración y estrategia existentes;
- progreso monotónico y cancelación del motor histórico.
