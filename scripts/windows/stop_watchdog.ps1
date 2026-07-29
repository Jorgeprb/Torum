$processIds = @(
  Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*services\watchdog*" -or $_.CommandLine -like "*uvicorn app.main*" } |
    ForEach-Object { $_.ProcessId }
)
$processIds += @(
  Get-NetTCPConnection -LocalPort 9200 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { $_.OwningProcess }
)

foreach ($processId in ($processIds | Sort-Object -Unique)) {
  Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
}
