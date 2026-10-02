$ErrorActionPreference='SilentlyContinue'
$root=Split-Path $PSScriptRoot -Parent
$pidFile="$root\state\coordinator_process.json"
function Stop-Tree([int]$Id){
  $children=Get-CimInstance Win32_Process|Where-Object{$_.ParentProcessId -eq $Id}
  foreach($c in $children){Stop-Tree ([int]$c.ProcessId)}
  Stop-Process -Id $Id -Force -ErrorAction SilentlyContinue
}
if(Test-Path $pidFile){
  try{
    $j=Get-Content $pidFile -Raw|ConvertFrom-Json;$id=[int]$j.pid
    $details=Get-CimInstance Win32_Process -Filter "ProcessId=$id"
    if($details){
      if($details.Name -notmatch '^python(w)?\.exe$' -or -not $details.CommandLine.Contains("$root\server\coordinator.py")){
        throw 'PID record does not identify this coordinator'
      }
      Stop-Tree $id;Write-Host "Coordinator stopped PID tree $id"
    }
  }catch{Write-Error $_ -ErrorAction Continue;exit 1}
  Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}else{Write-Host 'No coordinator PID file found'}
