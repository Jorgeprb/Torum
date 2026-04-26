# Futuro VPS Windows

La migracion futura mantendra la misma separacion:

- MT5 instalado en Windows VPS.
- `mt5_bridge` como proceso Python local.
- Backend, TimescaleDB y Redis en Docker Compose.
- Frontend servido como build estatico o por Vite solo en desarrollo.

Antes de migrar a VPS se debera cerrar:

- HTTPS.
- Secrets reales.
- Firewall.
- Backups de TimescaleDB.
- Supervision de procesos.
- Checklist de operativa LIVE.
