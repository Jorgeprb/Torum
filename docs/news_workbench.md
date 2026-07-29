# Centro de noticias

La configuración de noticias se concentra en una única interfaz con cinco vistas:

- Resumen
- Reglas
- Calendario
- Proveedor
- Importación

## Reglas por impacto

Cada impacto HIGH, MEDIUM o LOW configura:

- activación;
- minutos antes;
- minutos después;
- acción: mostrar, avisar, bloquear bot o bloquear todo.

Las divisas y símbolos se editan mediante chips. La política manual puede permitir, avisar, exigir aceptación o bloquear.

Las reglas se convierten en zonas persistentes. Torum V1 consulta directamente las zonas que bloquean; el booleano legado `block_trading_during_news` ya no puede desactivar silenciosamente una regla `BLOCK_BOT` del editor nuevo.

## Calendario

Permite filtrar, revisar y eliminar eventos. El estado del proveedor muestra última sincronización, resultados y errores.

## Importación

CSV y JSON se pueden arrastrar, previsualizar y confirmar. La edición JSON manual queda como opción avanzada.

## Concurrencia

`NewsSettings.revision` evita que una pestaña antigua sobrescriba reglas recientes. La API devuelve HTTP 409 ante conflicto.
