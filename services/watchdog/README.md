# Torum Watchdog

Servicio local Windows para comprobar estado y reiniciar Torum desde la UI admin.

No expone comandos libres. Solo acciones permitidas. El frontend no llama aqui: llama al backend.

## Instalar sin .env

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\set_torum_system_config.ps1 -WatchdogAdminToken "pon-token-largo" -Mt5Path "C:\Program Files\MetaTrader 5\terminal64.exe"

cd c:\Users\steel\Documents\Codex\Torum_App\torum\services\watchdog
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 9200
```

## Probar

```powershell
$token = "pon-tu-token"
Invoke-RestMethod http://127.0.0.1:9200/status -Headers @{Authorization="Bearer $token"}
```

## Seguridad

Usa `WATCHDOG_ADMIN_TOKEN` largo como variable de Windows. Deja `WATCHDOG_HOST=127.0.0.1` salvo que controles acceso por Tailscale/firewall.
