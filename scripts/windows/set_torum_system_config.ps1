param(
  [Parameter(Mandatory = $true)]
  [string]$WatchdogAdminToken,
  [string]$TorumRoot = "C:\Users\steel\Documents\Codex\Torum_App\torum",
  [string]$Mt5Path = "C:\Program Files\MetaTrader 5\terminal64.exe",
  [string]$WatchdogHost = "127.0.0.1",
  [int]$WatchdogPort = 9200,
  [int]$Mt5PollIntervalMs = 50,
  [int]$Mt5BatchFlushIntervalMs = 100,
  [string]$JwtSecretKey = "replace-with-a-long-random-secret",
  [string]$FrontendStartCmd = "cd apps\web; npm run dev:host",
  [switch]$Machine
)

$ErrorActionPreference = "Stop"
$scope = if ($Machine) { "Machine" } else { "User" }

function Set-TorumEnv {
  param([string]$Name, [string]$Value)
  [Environment]::SetEnvironmentVariable($Name, $Value, $scope)
  Set-Item -Path "Env:$Name" -Value $Value
}

Set-TorumEnv "WATCHDOG_ADMIN_TOKEN" $WatchdogAdminToken
Set-TorumEnv "WATCHDOG_HOST" $WatchdogHost
Set-TorumEnv "WATCHDOG_PORT" ([string]$WatchdogPort)
Set-TorumEnv "WATCHDOG_BASE_URL" "http://host.docker.internal:$WatchdogPort"
Set-TorumEnv "WATCHDOG_TIMEOUT_SECONDS" "5"
Set-TorumEnv "JWT_SECRET_KEY" $JwtSecretKey
Set-TorumEnv "CORS_ORIGINS" "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173,http://100.124.49.118:4173,http://172.27.176.1:4173,http://172.18.64.1:4173,http://192.168.1.86:4173,https://pc-oficina.tail652fa7.ts.net"
Set-TorumEnv "TORUM_ROOT" $TorumRoot
Set-TorumEnv "MT5_PATH" $Mt5Path
Set-TorumEnv "MT5_PROCESS_NAME" "terminal64.exe"
Set-TorumEnv "DOCKER_COMPOSE_FILE" "docker-compose.yml"
Set-TorumEnv "API_HEALTH_URL" "http://127.0.0.1:8000/api/health"
Set-TorumEnv "FRONTEND_HEALTH_URL" "http://127.0.0.1:5173"
Set-TorumEnv "BRIDGE_HEALTH_URL" "http://127.0.0.1:9100/health"
Set-TorumEnv "API_MT5_STATUS_URL" "http://127.0.0.1:8000/api/mt5/status"
Set-TorumEnv "MAX_TICK_AGE_SECONDS" "30"
Set-TorumEnv "STARTUP_DELAY_SECONDS" "6"
Set-TorumEnv "BRIDGE_PYTHON" "python"
Set-TorumEnv "FRONTEND_START_CMD" $FrontendStartCmd

# Queremos que Docker Compose vuelva a leer .env
[Environment]::SetEnvironmentVariable("COMPOSE_DISABLE_ENV_FILE", $null, $scope)
Remove-Item Env:COMPOSE_DISABLE_ENV_FILE -ErrorAction SilentlyContinue

Write-Host "Config Torum guardada en variables de Windows ($scope)."
Write-Host "Docker Compose leerá el archivo .env desde la raíz del repo."
Write-Host "Cierra y abre PowerShell antes de arrancar Docker/watchdog."
