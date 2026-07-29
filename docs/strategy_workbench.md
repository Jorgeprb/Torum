# Editor visual de Torum V1

Torum V1 se configura desde un pipeline fijo y validado. La interfaz no envía órdenes durante la edición.

## Flujo

```text
Motor y activo
  -> Mercado y horario
  -> Desbloqueo H2/H3
  -> Pullback M5
  -> Rectángulo operativo
  -> Confirmación alcista
  -> Noticias y DXY
  -> Soporte S1/S2/S3
  -> Riesgo y ATH
  -> Ejecución y TP
```

Todos los campos conocidos proceden de `TorumV1Params` y del esquema UI generado por el backend. El único campo no editable es `pullback_threshold_pct`, mantenido como alias interno de compatibilidad.

## Configuración común y overrides

- **Configuración común**: valores base compartidos.
- **XAUUSD / XAUEUR**: solo guardan los campos personalizados.
- `Heredado` elimina el override y vuelve al valor común.
- El estado habilitado y el modo PAPER/DEMO/LIVE se guardan por activo.

## Publicación segura

La edición ocurre en un borrador local. El bot no cambia hasta pulsar **Publicar cambios**. La actualización de XAUUSD y XAUEUR es atómica y utiliza revisión optimista. Una pestaña antigua recibe HTTP 409 y no sobrescribe una configuración más reciente.

Cada publicación crea una versión con:

- revisión;
- usuario;
- fecha;
- nota del cambio;
- parámetros completos;
- modo y estado del activo.

Las señales guardan `strategy_config_id` y `strategy_config_revision`.

## Simulación histórica

La simulación se ha movido fuera del editor de ajustes. Se abre desde el menú hamburguesa en **Simulador**. El laboratorio dedicado permite visualizar velas, operaciones, soportes, regiones, métricas, equity y la traza completa de decisiones sin modificar la configuración publicada.

La documentación completa está en [`docs/strategy_simulator.md`](strategy_simulator.md). Los endpoints antiguos de simulación puntual se conservan por compatibilidad interna, pero la interfaz principal utiliza `POST /api/strategies/torum-v1/backtest`.

## Importar, exportar y presets

La configuración puede exportarse como JSON e importarse de nuevo como borrador. Los presets Base, Conservador y Estricto aplican cambios visibles que deben revisarse y publicarse explícitamente.

## Endpoints

```text
GET   /api/strategies/torum-v1/configuration/schema
GET   /api/strategies/torum-v1/configuration
PATCH /api/strategies/torum-v1/configuration
POST  /api/strategies/torum-v1/simulate
POST  /api/strategies/torum-v1/simulate/history
POST  /api/strategies/torum-v1/backtest
GET   /api/strategy-configs/{id}/versions
POST  /api/strategy-configs/{id}/versions/{revision}/restore
GET   /api/strategies/torum-v1/pullbacks
```
