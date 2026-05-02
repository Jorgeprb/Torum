param(
  [string]$TaskName = "TorumStartup",
  [string]$TorumRoot = "C:\Users\steel\Documents\Codex\Torum_App\torum",
  [switch]$Unregister
)

$ErrorActionPreference = "Stop"

if ($Unregister) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  Write-Host "Tarea eliminada: $TaskName"
  exit 0
}

$scriptPath = Join-Path $TorumRoot "scripts\windows\start_torum.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -TorumRoot `"$TorumRoot`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force
Write-Host "Tarea registrada: $TaskName"
