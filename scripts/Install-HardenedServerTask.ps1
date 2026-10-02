param()
$ErrorActionPreference='Stop'
$id=[Security.Principal.WindowsIdentity]::GetCurrent()
$wp=New-Object Security.Principal.WindowsPrincipal($id)
if(-not $wp.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Run this script once as Administrator.'}
$root=Split-Path $PSScriptRoot -Parent
$svc='NT AUTHORITY\LOCAL SERVICE'
icacls $root /grant "${svc}:(OI)(CI)RX" /T /C | Out-Null
if($LASTEXITCODE -ne 0){throw 'Could not grant service read access'}
icacls "$root\state" /grant "${svc}:(OI)(CI)M" /T /C | Out-Null
if($LASTEXITCODE -ne 0){throw 'Could not grant service state access'}
icacls "$root\config\server.json" /grant "${svc}:R" | Out-Null
if($LASTEXITCODE -ne 0){throw 'Could not grant service configuration access'}
$run='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
Remove-ItemProperty -Path $run -Name 'EnigmaGridCoordinator' -ErrorAction SilentlyContinue
powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\Stop-Coordinator.ps1"
$action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$root+'\scripts\Start-Coordinator.ps1"')
$trigger=New-ScheduledTaskTrigger -AtStartup
$principal=New-ScheduledTaskPrincipal -UserId $svc -LogonType ServiceAccount -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'EnigmaGridCoordinatorHardened' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'EnigmaGridCoordinatorHardened'
Write-Host 'Hardened coordinator installed under LOCAL SERVICE.'
