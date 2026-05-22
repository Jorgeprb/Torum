Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like "*services\watchdog*" -or $_.CommandLine -like "*uvicorn app.main*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }