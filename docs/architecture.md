# Arquitectura Torum

Este documento fija las decisiones de arquitectura para evitar que se pierdan en fases futuras.

## Objetivo

Torum sera una PWA de trading enfocada inicialmente en activos de oro. La plataforma visualizara datos procedentes de MetaTrader 5, permitira preparar operativa manual controlada, conservar historico y dejar lista la base para noticias, zonas de no operar, indicadores personalizados, dibujos, estrategias y alertas push.

## Decision local inicial

La primera arquitectura ejecutable sera local sobre Windows:

```text
Windows local
  - MT5 abierto manualmente
  - mt5_bridge Python fuera de Docker
  - frontend React/Vite fuera de Docker

Docker Compose
  - backend FastAPI
  - PostgreSQL + TimescaleDB
  - Redis
```

El frontend se ejecuta con:

```powershell
npm run dev
```

Para acceso remoto por Tailscale:

```powershell
npm run dev:host
```

El backend se expone desde Docker con:

```text
API_BIND_HOST=0.0.0.0
```

## Componentes

### Frontend PWA

Ubicacion:

```text
apps/web
```

Responsabilidades:

- Login.
- Dashboard principal.
- Estado visible de conexion, modo y cuenta.
- Graficos en fases posteriores.
- Paneles de trading, noticias, indicadores, alertas y configuracion.
- Nunca ejecuta ordenes directamente.

### Backend FastAPI

Ubicacion:

```text
services/api
```

Responsabilidades:

- Autenticacion y autorizacion.
- API REST.
- WebSockets en fases posteriores.
- Persistencia.
- Validacion de ordenes.
- Coordinacion con MT5 bridge.
- Risk manager, news engine, indicators y strategy engine en fases posteriores.

### Base de datos

Servicio Docker:

```text
timescaledb
```

Responsabilidades:

- Usuarios.
- Simbolos.
- Mapeos de broker.
- Velas, ticks e historico.
- Noticias y zonas de no operar.
- Dibujos JSON.
- Ordenes, posiciones y auditoria.
- Configuraciones de indicadores, estrategias y alertas.

### Redis

Servicio Docker:

```text
redis
```

Uso inicial:

- Preparado, no intensivo en fase 1.

Uso futuro:

- Colas.
- Alertas.
- Estado efimero.
- Fan-out de eventos.

### MT5 Bridge

Ubicacion:

```text
services/mt5_bridge
```

Decision:

- Corre fuera de Docker en Windows.
- Usa el paquete Python `MetaTrader5`.
- Requiere MT5 abierto y logueado localmente.
- Desde fase 3 lee cuenta, simbolos y ticks.
- Desde fase 4 expone un servidor HTTP local para ordenes manuales solicitadas solo por el backend.
- `MT5_ALLOW_ORDER_EXECUTION=false` por defecto.

## Decision de datos de mercado

MT5 no mandara velas a Torum.

La fuente de verdad sera siempre:

```text
ticks crudos -> TimescaleDB -> CandleAggregator -> candles -> REST/WebSocket -> PWA
```

Las velas `M1`, `M5`, `H1`, `H2`, `H4`, `D1` y `W1` se construyen dentro del backend a partir de ticks. Esto evita depender de la construccion de velas del broker y deja un historico propio reproducible.

## Seguridad operativa

Reglas base:

- El frontend crea intenciones, no ordenes directas.
- El backend valida siempre antes de enviar al bridge.
- `PAPER` no envia ordenes reales.
- `DEMO` solo podra operar si MT5 esta conectado a cuenta demo.
- `LIVE` solo podra operar si MT5 esta conectado a cuenta real y con confirmacion visual fuerte.
- Si MT5 esta desconectado, no se opera.
- Si el precio esta desactualizado, no se opera.
- Si hay incoherencia entre modo configurado y cuenta MT5, se bloquea.
- Si el usuario activa bloqueo por noticias y hay zona activa, se bloquea.

## Noticias y zonas de no operar

La fuente inicial de noticias es manual mediante JSON/CSV. Torum normaliza eventos economicos y genera zonas por simbolo. Los proveedores automaticos quedan detras de una interfaz (`BaseNewsProvider`) para enchufar una fuente autorizada en el futuro.

Torum no usa scraping fragil como dependencia obligatoria de riesgo operativo.

## Roles

La decision actual es soportar solo:

- `admin`
- `trader`

No hay rol `viewer` en la fase 1.

## Tailscale

Tailscale se usara como red privada para acceso remoto.

Backend:

```text
API_BIND_HOST=0.0.0.0
PUBLIC_HOST=<ip-o-dns-tailscale>
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://<ip-o-dns-tailscale>:5173
```

Frontend:

```text
VITE_API_BASE_URL=http://<ip-o-dns-tailscale>:8000
VITE_WS_BASE_URL=ws://<ip-o-dns-tailscale>:8000
```

Arranque:

```powershell
npm run dev:host
```

## Flujo de ordenes

```text
Frontend
  -> intencion de orden
Backend
  -> auth
  -> validacion modo PAPER/DEMO/LIVE
  -> validacion cuenta MT5
  -> risk manager
  -> bloqueo noticias
  -> order manager
MT5 Bridge
  -> MetaTrader 5
Backend
  -> persistencia y evento
Frontend
  -> actualizacion visual
```

En Fase 4, `PAPER` queda completamente dentro del backend y base de datos. `DEMO` y `LIVE` usan el servidor local del bridge en `MT5_BRIDGE_BASE_URL`, normalmente `http://host.docker.internal:9100` cuando el backend corre en Docker.

## Fases

1. Base monorepo, Docker Compose, API, auth y PWA.
2. Simbolos, mapeos, velas, WebSocket y grafico mock.
3. MT5 bridge real para cuenta, simbolos y ticks.
4. Trading manual paper/demo/live con protecciones.
5. News engine y zonas de no operar.
6. Indicadores personalizados y SMA30.
7. Dibujos persistentes JSON.
8. Strategy engine, signals, risk manager y order manager.
9. Alertas push PWA.
10. Hardening, documentacion final y preparacion VPS Windows.
