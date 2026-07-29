param(
    [string]$TorumRoot = "",
    [string]$Mt5Path = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($TorumRoot)) {
    $TorumRoot = if ($env:TORUM_ROOT) {
        $env:TORUM_ROOT
    } else {
        "C:\Users\steel\Documents\Codex\Torum_App\torum"
    }
}

if ([string]::IsNullOrWhiteSpace($Mt5Path)) {
    $Mt5Path = if ($env:MT5_PATH) {
        $env:MT5_PATH
    } else {
        "C:\Program Files\MetaTrader 5\terminal64.exe"
    }
}

Set-Location $TorumRoot
$envFile = Join-Path $TorumRoot ".env"

if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()

        if ($line -eq "" -or $line.StartsWith("#")) {
            return
        }

        $parts = $line -split "=", 2

        if ($parts.Count -eq 2) {
            $name = $parts[0].Trim()
            $value = $parts[1].Trim().Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}
# IMPORTANTE:
# No desactivar .env. Docker Compose debe leer .env desde la raíz del repo.
Remove-Item Env:COMPOSE_DISABLE_ENV_FILE -ErrorAction SilentlyContinue

if (Test-Path $Mt5Path) {
    Start-Process -FilePath $Mt5Path
}

docker compose --env-file .env up -d timescaledb redis api

$bridgePath = Join-Path $TorumRoot "services\mt5_bridge"
$bridgePython = if ($env:BRIDGE_PYTHON) { $env:BRIDGE_PYTHON } else { "python" }

Start-Process `
    -WindowStyle Hidden `
    -WorkingDirectory $bridgePath `
    -FilePath $bridgePython `
    -ArgumentList "-m bridge.main"

$watchdogPath = Join-Path $TorumRoot "services\watchdog"
$watchdogVenvPython = Join-Path $watchdogPath ".venv\Scripts\python.exe"
$watchdogPython = if ($env:WATCHDOG_PYTHON) {
    $env:WATCHDOG_PYTHON
} elseif (Test-Path -LiteralPath $watchdogVenvPython) {
    $watchdogVenvPython
} else {
    "python"
}
$watchdogHost = if ($env:WATCHDOG_HOST) { $env:WATCHDOG_HOST } else { "0.0.0.0" }
$watchdogPort = if ($env:WATCHDOG_PORT) { $env:WATCHDOG_PORT } else { "9200" }

Start-Process `
    -WindowStyle Hidden `
    -WorkingDirectory $watchdogPath `
    -FilePath $watchdogPython `
    -ArgumentList "-m uvicorn app.main:app --host $watchdogHost --port $watchdogPort"
