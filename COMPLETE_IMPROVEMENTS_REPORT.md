# Torum — integración completa de mejoras

## Alcance

Esta versión integra el rediseño de ajustes, el editor visual de estrategia, simuladores sin órdenes, centro unificado de noticias, configuración tipada/versionada, separación de responsabilidades frontend, estado distribuido opcional y endurecimiento de pruebas/CI.

## Estrategia Torum V1

- `TorumV1Params` es la fuente única de verdad.
- Los 77 parámetros editables se generan desde el backend; `pullback_threshold_pct` queda oculto como alias interno.
- Validación cruzada de ATH, soportes, horarios y rangos.
- Configuración común y overrides por XAUUSD/XAUEUR.
- Estado y modo de ejecución por activo.
- Guardado atómico con revisión optimista.
- Historial de versiones y restauración.
- Señales etiquetadas con la revisión que las generó.
- Pipeline visual dividido en mercado, desbloqueo, pullback, zona, confirmación, contexto, soportes, riesgo y ejecución.
- Presets Base/Conservador/Estricto.
- Importación/exportación JSON.

## Simulación

- Simulador actual con trazabilidad paso a paso y sin envío de órdenes.
- Replay técnico de 500 velas M5.
- El replay deduplica setups y declara sus límites: no simula rentabilidad, balance/riesgo ni DXY históricos.

## Ajustes

- Secciones por dominio y búsqueda.
- Distinción entre dispositivo, cuenta y sistema.
- Modo sencillo/avanzado.
- Borrador, descartar y aplicar.
- Preferencias visuales inmediatas y ajustes operativos explícitos.

## Noticias

- UI unificada de reglas, calendario, proveedor e importación.
- Reglas por impacto con acciones DISPLAY/WARN/BLOCK_BOT/BLOCK_ALL.
- Política específica para trading manual.
- Chips para divisas y símbolos.
- Revisión optimista.
- Torum V1 respeta las zonas materializadas por impacto.

## Frontend y arquitectura

- Cliente HTTP común con JWT, timeout, cancelación, reintentos, request ID y errores tipados.
- Navegación hash con rutas directas.
- Extracción de paneles del workspace.
- Extracción de presentación de operaciones y marcadores.
- Hook de reanudación PWA.
- Hook independiente para BID/ASK, desacoplado de velas y overlays.
- Componentes dedicados para campos, trazas, versiones y replay.

## Estado distribuido y concurrencia

- `HybridLock`: lock local más lease Redis para evitar ejecuciones simultáneas de Torum V1 por símbolo.
- MT5 status replicado opcionalmente en Redis con fallback local.
- Pullbacks cacheados localmente y en Redis, con invalidación por usuario/símbolo.
- WebSocket fan-out local más pub/sub Redis opcional entre workers.
- Se conserva single-worker por defecto mientras schedulers y worker de jobs sean internos; puede externalizarse antes de desactivar la protección.

## Pruebas y CI

- Suite backend ampliada para editor, versionado, rollback, restauración, noticias, simulador y replay.
- Workflow GitHub Actions para compileall, pytest, typecheck y build.
- TypeScript estricto mediante `npm run typecheck`.

## Migración

Nueva cabeza Alembic:

```text
0022_strategy_workbench
```

Aplicar:

```bash
docker compose up -d timescaledb redis
docker compose run --rm api alembic upgrade head
```

## Verificaciones realizadas

- Backend: 190 pruebas superadas.
- Python `compileall`: correcto.
- TypeScript `tsc --noEmit`: correcto.
- `git diff --check`: sin errores de whitespace; solo avisos esperados de CRLF en scripts PowerShell.

## Limitaciones de validación

No se realizó una orden real contra MetaTrader 5 desde este entorno. El build Vite local no se pudo validar con el `node_modules` aportado porque falta el paquete binario opcional de Rollup para Linux; el CI y una instalación limpia con `npm ci` instalan el binario correcto.
