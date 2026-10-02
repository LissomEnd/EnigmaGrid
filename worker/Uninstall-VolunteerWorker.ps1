param([string]$InstallDir="$env:LOCALAPPDATA\EnigmaVolunteerGrid")
$ErrorActionPreference="SilentlyContinue"
$state="$InstallDir\client.json"
$worker="$InstallDir\worker\worker.py"
if((Test-Path $state) -and (Test-Path $worker)){
  $py=(Get-Command py -ErrorAction SilentlyContinue).Source
  if($py){ & $py -3.13 $worker --state $state --disable | Out-Host }
}
$runKey="HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
Remove-ItemProperty -Path $runKey -Name "EnigmaVolunteerGrid" -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$InstallDir*worker.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500
Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Removed. Contribution history remains on the server."