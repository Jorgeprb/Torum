param(
  [string]$TorumRoot = "",
  [string]$Mt5Path = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($TorumRoot)) {
  $TorumRoot = if ($env:TORUM_ROOT) { $env:TORUM_ROOT } else { "C:\Users\steel\Documents\Codex\Torum_App\torum" }
}

if ([string]::IsNullOrWhiteSpace($Mt5Path)) {
  $Mt5Path = if ($env:MT5_PATH) { $env:MT5_PATH } else { "C:\Program Files\MetaTrader 5\terminal64.exe" }
}

Set-Location $TorumRoot
$env:COMPOSE_DISABLE_ENV_FILE = "true"

if (Test-Path $Mt5Path) {
  Start-Process -FilePath $Mt5Path
}

docker compose up -d timescaledb redis api

$bridgePath = Join-Path $TorumRoot "services\mt5_bridge"
$bridgePython = if ($env:BRIDGE_PYTHON) { $env:BRIDGE_PYTHON } else { "python" }
Start-Process -WindowStyle Hidden -WorkingDirectory $bridgePath -FilePath $bridgePython -ArgumentList "-m bridge.main"

$watchdogPath = Join-Path $TorumRoot "services\watchdog"
$watchdogPython = if ($env:WATCHDOG_PYTHON) { $env:WATCHDOG_PYTHON } else { "python" }
$watchdogHost = if ($env:WATCHDOG_HOST) { $env:WATCHDOG_HOST } else { "127.0.0.1" }
$watchdogPort = if ($env:WATCHDOG_PORT) { $env:WATCHDOG_PORT } else { "9200" }
Start-Process -WindowStyle Hidden -WorkingDirectory $watchdogPath -FilePath $watchdogPython -ArgumentList "-m uvicorn app.main:app --host $watchdogHost --port $watchdogPort"
