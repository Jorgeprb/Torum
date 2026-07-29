# Integración final de la página Simulador

## Resultado

El modo simulador queda concentrado en la ruta `#/strategy/simulator`, accesible desde **Simulador** en el menú hamburguesa y en la navegación lateral de escritorio. No es necesario activar ningún modo adicional en Ajustes.

## Cambios de interfaz

- Configuración guiada en cuatro pasos: Mercado, Condiciones, Parámetros y Ejecución.
- Tarjeta fija de resumen con el botón principal **Ejecutar simulación**.
- Perfiles Realista, Conservador y Solo técnico.
- Selección individual y persistente por activo de regiones Torum y soportes S1/S2/S3.
- Recarga de dibujos y acceso directo al gráfico cuando falta una región o soporte.
- Editor temporal de todos los parámetros de Torum V1 sin publicar cambios.
- Validación previa con errores bloqueantes, avisos e indicaciones para corregirlos.
- Persistencia local del borrador del escenario.
- Progreso por fase, porcentaje, cancelación y recuperación de un trabajo en curso.
- Explicación específica cuando la simulación termina sin operaciones.
- Resultados organizados en gráfico/métricas, operaciones, depuración y cobertura.
- Diseño responsive para escritorio, tableta y móvil.

## Motor utilizado

La pantalla usa la cola histórica existente:

- `POST /api/strategies/torum-v1/backtest/jobs`
- `GET /api/strategies/torum-v1/backtest/jobs/{job_id}`
- `DELETE /api/strategies/torum-v1/backtest/jobs/{job_id}`

El motor permanece aislado: no crea señales, órdenes ni posiciones y no modifica MetaTrader ni la configuración publicada.

## Validaciones realizadas

- `npm run typecheck`: correcto.
- `pytest -q services/api/tests/test_strategy_backtest.py services/api/tests/test_strategy_workbench.py`: 11 pruebas superadas.
- `python -m compileall` sobre estrategia, dibujos y gráfico: correcto.
- Revisión de espacios y `git diff --check`: correcto.

El build Vite no pudo ejecutarse con el `node_modules` incluido en el ZIP original porque pertenece a otra plataforma y no contiene el binario opcional `@rollup/rollup-linux-x64-gnu`. El código TypeScript sí compila. En una instalación limpia debe ejecutarse `npm ci` antes de `npm run build`.
