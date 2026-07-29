param(
    [ValidateRange(1, 10080)]
    [int]$Minutes = 180
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$logRoot = Join-Path $projectRoot "logs"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$staging = Join-Path $env:TEMP "torum_logs_$timestamp"
$outputZip = Join-Path $projectRoot "torum_logs_$timestamp.zip"
$cutoff = (Get-Date).AddMinutes(-$Minutes)

New-Item -ItemType Directory -Force -Path $staging | Out-Null

try {
    if (Test-Path $logRoot) {
        Get-ChildItem -Path $logRoot -Recurse -File |
            Where-Object { $_.LastWriteTime -ge $cutoff } |
            ForEach-Object {
                $relative = $_.FullName.Substring($logRoot.Length).TrimStart('\', '/')
                $destination = Join-Path (Join-Path $staging "files") $relative
                New-Item -ItemType Directory -Force -Path (Split-Path $destination -Parent) | Out-Null
                Copy-Item $_.FullName $destination -Force
            }
    }

    Push-Location $projectRoot
    try {
        docker compose ps 2>&1 | Out-File -FilePath (Join-Path $staging "docker_compose_ps.txt") -Encoding utf8
        docker compose logs --no-color --since "${Minutes}m" api 2>&1 |
            Out-File -FilePath (Join-Path $staging "docker_api_last_${Minutes}m.log") -Encoding utf8
    }
    catch {
        $_ | Out-String | Out-File -FilePath (Join-Path $staging "docker_export_error.txt") -Encoding utf8
    }
    finally {
        Pop-Location
    }

    @(
        "GeneratedAt=$(Get-Date -Format o)",
        "WindowMinutes=$Minutes",
        "ProjectRoot=$projectRoot",
        "PersistentLogRoot=$logRoot"
    ) | Out-File -FilePath (Join-Path $staging "manifest.txt") -Encoding utf8

    if (Test-Path $outputZip) {
        Remove-Item $outputZip -Force
    }
    Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $outputZip -CompressionLevel Optimal
    Write-Host "Logs exportados en: $outputZip" -ForegroundColor Green
}
finally {
    Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
}
