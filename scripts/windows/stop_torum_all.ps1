param(
    [string]$TorumRoot = "",
    [int[]]$Ports = @(4173, 5173, 8000, 9100, 9200),
    [switch]$KeepMt5,
    [switch]$KeepTailscaleServe,
    [switch]$StopDockerDesktop
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

    return $null
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
        Stop-ProcessSafe -ProcessId $processId -Label "$Label puerto $Port"
    }
}

function Stop-ProcessSafe {
    param(
        [int]$ProcessId,
        [string]$Label
    )

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) {
        return
    }

    Write-Host "Paro $Label. PID $ProcessId"
    try {
        if ($process.MainWindowHandle -ne 0) {
            [void]$process.CloseMainWindow()
            Start-Sleep -Milliseconds 800
            $process.Refresh()
        }

        if (-not $process.HasExited) {
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Stop-ProcessesByCommandLine {
    param(
        [string]$Pattern,
        [string]$Label
    )

    $matches = Get-CimInstance Win32_Process |
        Where-Object {
            $_.ProcessId -ne $PID -and
            $_.CommandLine -and
            $_.CommandLine -like $Pattern
        }

    foreach ($match in $matches) {
        Stop-ProcessSafe -ProcessId ([int]$match.ProcessId) -Label $Label
    }
}

function Stop-Mt5 {
    $processes = Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -ieq "terminal64.exe" -or
            $_.Name -ieq "terminal.exe"
        }

    foreach ($process in $processes) {
        Stop-ProcessSafe -ProcessId ([int]$process.ProcessId) -Label "MT5"
    }
}

function Stop-TailscaleServe {
    $tailscalePath = Get-ToolPath -Name "tailscale.exe" -Fallbacks @(
        "C:\Program Files\Tailscale\tailscale.exe",
        "$env:LOCALAPPDATA\Tailscale\tailscale.exe"
    )

    if (-not $tailscalePath) {
        Write-Host "Tailscale no encontrado. Salto serve reset."
        return
    }

    Write-Host "Reseteo Tailscale Serve"
    & $tailscalePath serve reset --yes
}

if ([string]::IsNullOrWhiteSpace($TorumRoot)) {
    $TorumRoot = if ($env:TORUM_ROOT) {
        $env:TORUM_ROOT
    } else {
        (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    }
}

$TorumRoot = (Resolve-Path $TorumRoot).Path
$webPath = Join-Path $TorumRoot "apps\web"
$bridgePath = Join-Path $TorumRoot "services\mt5_bridge"
$watchdogPath = Join-Path $TorumRoot "services\watchdog"

Set-Location $TorumRoot
Import-DotEnv -Path (Join-Path $TorumRoot ".env")
Remove-Item Env:COMPOSE_DISABLE_ENV_FILE -ErrorAction SilentlyContinue

Write-Host "Torum root: $TorumRoot"

if (-not $KeepTailscaleServe) {
    Write-Step "Tailscale Serve"
    Stop-TailscaleServe
}

Write-Step "Docker compose"
$dockerPath = Get-ToolPath -Name "docker"
if ($dockerPath) {
    try {
        & $dockerPath compose --env-file .env down --remove-orphans
    } catch {
        Write-Host "Docker compose no pudo parar: $($_.Exception.Message)"
    }
} else {
    Write-Host "Docker no encontrado. Salto Docker."
}

Write-Step "Procesos Torum por ruta"
Stop-ProcessesByCommandLine -Pattern "*$webPath*" -Label "frontend Torum"
Stop-ProcessesByCommandLine -Pattern "*$bridgePath*" -Label "mt5_bridge Torum"
Stop-ProcessesByCommandLine -Pattern "*$watchdogPath*" -Label "watchdog Torum"

Write-Step "Puertos Torum"
foreach ($port in $Ports) {
    Stop-PortProcess -Port $port -Label "Torum"
}

if (-not $KeepMt5) {
    Write-Step "MT5"
    Stop-Mt5
}

if ($StopDockerDesktop) {
    Write-Step "Docker Desktop"
    Get-Process -Name "Docker Desktop", "com.docker.backend" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-ProcessSafe -ProcessId $_.Id -Label $_.ProcessName }
}

Write-Host ""
Write-Host "Torum parado."
Write-Host "Datos Docker conservados. Volumenes no borrados."
