# Torum Watchdog

Servicio local Windows para comprobar estado y reiniciar Torum desde la UI admin.

No expone comandos libres. Solo acciones permitidas. El frontend no llama aqui: llama al backend.

## Instalar sin .env

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\set_torum_system_config.ps1 -WatchdogAdminToken "pon-token-largo" -Mt5Path "C:\Program Files\MetaTrader 5\terminal64.exe"

cd c:\Users\steel\Documents\Codex\Torum_App\torum\services\watchdog
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 9200
```

Si ves `Invalid watchdog token`:

```powershell
cd c:\Users\steel\Documents\Codex\Torum_App\torum
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\sync_watchdog_token_from_api.ps1
```

## Probar

```powershell
$token = "pon-tu-token"
Invoke-RestMethod http://127.0.0.1:9200/status -Headers @{Authorization="Bearer $token"}
```

## Seguridad

Usa `WATCHDOG_ADMIN_TOKEN` largo como variable de Windows. `WATCHDOG_HOST=0.0.0.0` permite que Docker llegue mediante `host.docker.internal`. No publiques el puerto 9200 en Internet.
