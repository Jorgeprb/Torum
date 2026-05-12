param(
  [string]$TorumRoot = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($TorumRoot)) {
  $TorumRoot = if ($env:TORUM_ROOT) { $env:TORUM_ROOT } else { "C:\Users\steel\Documents\Codex\Torum_App\torum" }
}

$token = docker exec torum-api printenv WATCHDOG_ADMIN_TOKEN
if ([string]::IsNullOrWhiteSpace($token)) {
  throw "WATCHDOG_ADMIN_TOKEN no existe dentro de torum-api"
}

[Environment]::SetEnvironmentVariable("WATCHDOG_ADMIN_TOKEN", $token.Trim(), [EnvironmentVariableTarget]::User)
$env:WATCHDOG_ADMIN_TOKEN = $token.Trim()

powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $TorumRoot "scripts\windows\restart_watchdog.ps1") -TorumRoot $TorumRoot
Write-Host "Token watchdog sincronizado desde torum-api."
