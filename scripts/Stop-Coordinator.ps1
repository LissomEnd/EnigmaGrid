$ErrorActionPreference='SilentlyContinue'
$root=Split-Path $PSScriptRoot -Parent
$pidFile="$root\state\coordinator_process.json"
function Stop-Tree([int]$Id){
  $children=Get-CimInstance Win32_Process|Where-Object{$_.ParentProcessId -eq $Id}
  foreach($c in $children){Stop-Tree ([int]$c.ProcessId)}
  Stop-Process -Id $Id -Force -ErrorAction SilentlyContinue
}
if(Test-Path $pidFile){
  try{$j=Get-Content $pidFile -Raw|ConvertFrom-Json;$id=[int]$j.pid;Stop-Tree $id;Write-Host "Coordinator stopped PID tree $id"}catch{}
  Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}else{Write-Host 'No coordinator PID file found'}
