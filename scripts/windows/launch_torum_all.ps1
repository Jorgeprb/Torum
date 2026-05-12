param(
    [string]$TorumRoot = "",
    [string]$Mt5Path = "",
    [string]$PublicUrl = "https://pc-oficina.tail652fa7.ts.net",
    [int]$FrontendPort = 4173,
    [int]$BridgePort = 9100,
    [int]$WatchdogPort = 9200,
    [int]$ApiPort = 8000,
    [int]$ApiHttpsPort = 8000,
    [string]$DockerDesktopPath = "",
    [switch]$NoDockerBuild,
    [switch]$NoFrontendBuild,
    [switch]$SkipMt5,
    [switch]$SkipDocker,
    [switch]$SkipFrontend,
    [switch]$SkipBridge,
    [switch]$SkipWatchdog,
    [switch]$SkipTailscaleServe,
    [switch]$ResetTailscaleServe
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Import-DotEnv {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()

        if ($line -eq "" -or $line.StartsWith("#")) {
            return
        }

        $parts = $line -split "=", 2

        if ($parts.Count -ne 2) {
            return
        }

        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")

        if ($name -ne "") {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Set-ProcessEnv {
    param(
        [string]$Name,
        [string]$Value
    )

    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
}

function Get-ToolPath {
    param(
        [string]$Name,
        [string[]]$Fallbacks = @()
    )

    $cmd = Get-Command $Name -ErrorAction SilentlyContinue

    if ($cmd) {
        return $cmd.Source
    }

    foreach ($fallback in $Fallbacks) {
        if (Test-Path $fallback) {
            return $fallback
        }
    }

    throw "No encuentro herramienta: $Name"
}

function Get-UrlWithPort {
    param(
        [string]$Url,
        [int]$Port
    )

    $builder = [System.UriBuilder]::new($Url)
    $builder.Port = $Port
    return $builder.Uri.AbsoluteUri.TrimEnd("/")
}

function Get-WebSocketUrl {
    param([string]$Url)

    return $Url -replace "^https://", "wss://" -replace "^http://", "ws://"
}

function Test-DockerReady {
    param([string]$DockerPath)

    try {
        & $DockerPath info 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Start-DockerDesktopIfNeeded {
    param(
        [string]$DockerPath,
        [string]$DesktopPath,
        [int]$TimeoutSeconds = 120
    )

    if (Test-DockerReady -DockerPath $DockerPath) {
        Write-Host "Docker ya vivo"
        return
    }

    $candidates = @()

    if (-not [string]::IsNullOrWhiteSpace($DesktopPath)) {
        $candidates += $DesktopPath
    }

    if ($env:DOCKER_DESKTOP_PATH) {
        $candidates += $env:DOCKER_DESKTOP_PATH
    }

    $candidates += @(
        "C:\Program Files\Docker\Docker\Docker Desktop.exe",
        "$env:LOCALAPPDATA\Programs\Docker\Docker\Docker Desktop.exe"
    )

    $desktop = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $desktop) {
        throw "Docker no responde y no encuentro Docker Desktop."
    }

    Write-Host "Lanzo Docker Desktop"
    Start-Process -FilePath $desktop

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        if (Test-DockerReady -DockerPath $DockerPath) {
            Write-Host "Docker listo"
            return
        }

        Start-Sleep -Seconds 2
    }

    throw "Docker no arranco a tiempo."
}

function Stop-PortProcess {
    param(
        [int]$Port,
        [string]$Label
    )

    $pids = @()
    $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)$"

    netstat -ano -p tcp | ForEach-Object {
        if ($_ -match $pattern) {
            $pids += [int]$Matches[1]
        }
    }

    $pids = $pids | Sort-Object -Unique | Where-Object { $_ -ne $PID }

    foreach ($processId in $pids) {
        Write-Host "Paro $Label en puerto $Port. PID $processId"
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

function Start-HiddenProcess {
    param(
        [string]$Label,
        [string]$WorkingDirectory,
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Host "Lanzo $Label"
    Start-Process `
        -WindowStyle Hidden `
        -WorkingDirectory $WorkingDirectory `
        -FilePath $FilePath `
        -ArgumentList $Arguments
}

function Start-Mt5Visible {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        Write-Host "MT5 no encontrado: $Path"
        return
    }

    Write-Host "Lanzo MT5"
    Start-Process -FilePath $Path
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [string]$Label,
        [int]$TimeoutSeconds = 40
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                Write-Host "$Label responde en $Url"
                return $true
            }
        } catch {
            Start-Sleep -Milliseconds 700
        }
    }

    Write-Host "$Label NO responde en $Url"
    return $false
}

function Configure-TailscaleServe {
    param(
        [string]$TailscalePath,
        [int]$FrontendPort,
        [int]$ApiPort,
        [int]$ApiHttpsPort,
        [switch]$Reset
    )

    Write-Step "Tailscale Serve"

    $frontendTarget = "http://127.0.0.1:$FrontendPort"
    $apiTarget = "http://127.0.0.1:$ApiPort"

    if ($Reset) {
        Write-Host "Reseteo configuracion anterior de Tailscale Serve"
        & $TailscalePath serve reset --yes
    }

    Write-Host "Configuro frontend: https://... -> $frontendTarget"
    & $TailscalePath serve --bg --yes --https=443 $frontendTarget

    Write-Host "Configuro API: https://...:$ApiHttpsPort -> $apiTarget"
    & $TailscalePath serve --bg --yes --https=$ApiHttpsPort $apiTarget

    Write-Host ""
    Write-Host "Estado Tailscale Serve:"
    & $TailscalePath serve status
}

if ([string]::IsNullOrWhiteSpace($TorumRoot)) {
    $TorumRoot = if ($env:TORUM_ROOT) {
        $env:TORUM_ROOT
    } else {
        (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    }
}

$TorumRoot = (Resolve-Path $TorumRoot).Path
Set-Location $TorumRoot

Import-DotEnv -Path (Join-Path $TorumRoot ".env")
Remove-Item Env:COMPOSE_DISABLE_ENV_FILE -ErrorAction SilentlyContinue

if ([string]::IsNullOrWhiteSpace($Mt5Path)) {
    $Mt5Path = if ($env:MT5_PATH) {
        $env:MT5_PATH
    } else {
        "C:\Program Files\MetaTrader 5\terminal64.exe"
    }
}

$pythonPath = Get-ToolPath -Name "python"
$npmPath = Get-ToolPath -Name "npm.cmd" -Fallbacks @(
    "C:\Program Files\nodejs\npm.cmd"
)
$dockerPath = Get-ToolPath -Name "docker"
$tailscalePath = $null

if (-not $SkipTailscaleServe) {
    $tailscalePath = Get-ToolPath -Name "tailscale.exe" -Fallbacks @(
        "C:\Program Files\Tailscale\tailscale.exe",
        "$env:LOCALAPPDATA\Tailscale\tailscale.exe"
    )
}

$webPath = Join-Path $TorumRoot "apps\web"
$bridgePath = Join-Path $TorumRoot "services\mt5_bridge"
$watchdogPath = Join-Path $TorumRoot "services\watchdog"

Write-Host "Torum root: $TorumRoot"
Write-Host "Public URL: $PublicUrl"

$publicApiUrl = Get-UrlWithPort -Url $PublicUrl -Port $ApiHttpsPort

# Variables para que Docker/API y frontend funcionen con el dominio HTTPS de Tailscale.
Set-ProcessEnv "TAILSCALE_ENABLED" "true"
Set-ProcessEnv "PUBLIC_HOST" ($PublicUrl -replace "^https?://", "")
Set-ProcessEnv "API_BIND_HOST" "0.0.0.0"
Set-ProcessEnv "API_PORT" "$ApiPort"
Set-ProcessEnv "WATCHDOG_BASE_URL" "http://host.docker.internal:$WatchdogPort"
Set-ProcessEnv "WATCHDOG_TIMEOUT_SECONDS" "5"

# Importante para watchdog: si no, seguirá mirando 5173 por defecto.
Set-ProcessEnv "FRONTEND_HEALTH_URL" "http://127.0.0.1:$FrontendPort"

# Importante para Vite build: el movil entra por HTTPS 443,
# pero la API se sirve por HTTPS $ApiHttpsPort.
Set-ProcessEnv "VITE_API_BASE_URL" "$publicApiUrl"
Set-ProcessEnv "VITE_WS_BASE_URL" (Get-WebSocketUrl -Url $publicApiUrl)

if (-not $SkipMt5) {
    Write-Step "MT5"
    Start-Mt5Visible -Path $Mt5Path
}

if (-not $SkipDocker) {
    Write-Step "Docker API + DB + Redis"
    Start-DockerDesktopIfNeeded -DockerPath $dockerPath -DesktopPath $DockerDesktopPath

    $composeArgs = @("compose", "--env-file", ".env", "up", "-d")

    if (-not $NoDockerBuild) {
        $composeArgs += "--build"
    }

    $composeArgs += @("timescaledb", "redis", "api")
    & $dockerPath @composeArgs

    Wait-HttpOk -Url "http://127.0.0.1:$ApiPort/api/health" -Label "API/backend" -TimeoutSeconds 60 | Out-Null
}

if (-not $SkipFrontend) {
    Write-Step "Frontend produccion"
    Stop-PortProcess -Port $FrontendPort -Label "frontend"

    if (-not $NoFrontendBuild) {
        & $npmPath --prefix $webPath run build
    }

    Start-HiddenProcess `
        -Label "frontend preview" `
        -WorkingDirectory $webPath `
        -FilePath $npmPath `
        -Arguments @("run", "preview", "--", "--host", "0.0.0.0", "--port", "$FrontendPort", "--strictPort")

    $frontendOk = Wait-HttpOk -Url "http://127.0.0.1:$FrontendPort/" -Label "Frontend" -TimeoutSeconds 40

    if (-not $frontendOk) {
        throw "El frontend no responde en http://127.0.0.1:$FrontendPort/. Si Tailscale apunta a ese puerto, dara 502."
    }
}

if (-not $SkipBridge) {
    Write-Step "MT5 bridge"
    Stop-PortProcess -Port $BridgePort -Label "mt5_bridge"

    $bridgePython = if ($env:BRIDGE_PYTHON) { $env:BRIDGE_PYTHON } else { $pythonPath }

    Start-HiddenProcess `
        -Label "mt5_bridge" `
        -WorkingDirectory $bridgePath `
        -FilePath $bridgePython `
        -Arguments @("-m", "bridge.main")

    Wait-HttpOk -Url "http://127.0.0.1:$BridgePort/health" -Label "Bridge" -TimeoutSeconds 30 | Out-Null
}

if (-not $SkipWatchdog) {
    Write-Step "Watchdog"
    Stop-PortProcess -Port $WatchdogPort -Label "watchdog"

    $watchdogPython = if ($env:WATCHDOG_PYTHON) { $env:WATCHDOG_PYTHON } else { $pythonPath }

    # Para poder consultar desde el propio PC y desde la API via host.docker.internal.
    # Si quieres cerrarlo mas, usa 127.0.0.1; para diagnostico remoto, 0.0.0.0 va mejor.
    $watchdogHost = if ($env:WATCHDOG_HOST) { $env:WATCHDOG_HOST } else { "0.0.0.0" }

    Start-HiddenProcess `
        -Label "watchdog" `
        -WorkingDirectory $watchdogPath `
        -FilePath $watchdogPython `
        -Arguments @("-m", "uvicorn", "app.main:app", "--host", $watchdogHost, "--port", "$WatchdogPort")

    Wait-HttpOk -Url "http://127.0.0.1:$WatchdogPort/status" -Label "Watchdog" -TimeoutSeconds 30 | Out-Null
}

if (-not $SkipTailscaleServe) {
    $serveOk = Wait-HttpOk -Url "http://127.0.0.1:$FrontendPort/" -Label "Frontend antes de Tailscale Serve" -TimeoutSeconds 10

    if (-not $serveOk) {
        throw "No configuro Tailscale Serve porque el frontend local no responde. Esto causaria 502."
    }

    Configure-TailscaleServe `
        -TailscalePath $tailscalePath `
        -FrontendPort $FrontendPort `
        -ApiPort $ApiPort `
        -ApiHttpsPort $ApiHttpsPort `
        -Reset:$ResetTailscaleServe
}

Write-Host ""
Write-Host "Torum lanzado."
Write-Host "Frontend local: http://127.0.0.1:$FrontendPort/"
Write-Host "API local: http://127.0.0.1:$ApiPort/api/health"
Write-Host "API Tailscale: $publicApiUrl/api/health"
Write-Host "Watchdog: http://127.0.0.1:$WatchdogPort/status"
Write-Host "Bridge: http://127.0.0.1:$BridgePort/health"
Write-Host "Tailscale/Tailgate: $PublicUrl/"
Write-Host ""
Write-Host "Si sigue saliendo 502, ejecuta:"
Write-Host "  tailscale serve status"
Write-Host "  Invoke-WebRequest http://127.0.0.1:$FrontendPort/ -UseBasicParsing"
