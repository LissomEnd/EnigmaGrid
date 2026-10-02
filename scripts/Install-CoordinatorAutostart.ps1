$root=Split-Path $PSScriptRoot -Parent
$run='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$cmd='powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$root+'\scripts\Start-Coordinator.ps1"'
New-Item -Path $run -Force|Out-Null
Set-ItemProperty -Path $run -Name 'EnigmaGridCoordinator' -Value $cmd
Write-Host 'Coordinator autostart installed for this Windows user.'
