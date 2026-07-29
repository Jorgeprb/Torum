param(
  [string]$TorumRoot = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($TorumRoot)) {
  $TorumRoot = if ($env:TORUM_ROOT) { $env:TORUM_ROOT } else { "C:\Users\steel\Documents\Codex\Torum_App\torum" }
}

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
$escapedWatchdogPath = [Regex]::Escape($watchdogPath)

$processes = Get-CimInstance Win32_Process |
  Where-Object {
    $_.CommandLine -match "uvicorn" -and
    $_.CommandLine -match "app\.main:app" -and
    ($_.CommandLine -match $escapedWatchdogPath -or $_.ExecutablePath -match "python")
  }

$processIds = @($processes | ForEach-Object { $_.ProcessId })
$processIds += @(
  Get-NetTCPConnection -LocalPort ([int]$watchdogPort) -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { $_.OwningProcess }
)

foreach ($processId in ($processIds | Sort-Object -Unique)) {
  try {
    Stop-Process -Id $processId -Force -ErrorAction Stop
  } catch {
    Write-Warning "No se pudo detener watchdog PID ${processId}: $($_.Exception.Message)"
  }
}

Start-Sleep -Seconds 1
Start-Process -WindowStyle Hidden -WorkingDirectory $watchdogPath -FilePath $watchdogPython -ArgumentList "-m uvicorn app.main:app --host $watchdogHost --port $watchdogPort"
Write-Host "Watchdog reiniciado en http://${watchdogHost}:$watchdogPort"
