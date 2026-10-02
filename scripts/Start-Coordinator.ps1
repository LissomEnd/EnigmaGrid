$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$py="$root\.venv-server\Scripts\python.exe"
$pidFile="$root\state\coordinator_process.json"
if(Test-Path $pidFile){
  try{$old=Get-Content $pidFile -Raw|ConvertFrom-Json;$proc=Get-Process -Id ([int]$old.pid) -ErrorAction SilentlyContinue}catch{$proc=$null}
  if($proc){
    $details=Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)"
    if($details.Name -match '^python(w)?\.exe$' -and $details.CommandLine.Contains("$root\server\coordinator.py")){
      Write-Host "Coordinator already running PID $($proc.Id)";exit 0
    }
    throw 'Coordinator PID record refers to another process; inspect it before restarting'
  }
}
$out="$root\state\coordinator.stdout.log";$err="$root\state\coordinator.stderr.log"
$cache="$root\state\numba-cache";New-Item -ItemType Directory -Force $cache|Out-Null
$env:PYTHONDONTWRITEBYTECODE="1"
$env:NUMBA_CACHE_DIR=$cache
$p=Start-Process -FilePath $py -ArgumentList @("$root\server\coordinator.py") -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
@{pid=$p.Id;started=(Get-Date).ToString('o');stdout=$out;stderr=$err}|ConvertTo-Json|Set-Content $pidFile
Write-Host "Coordinator started PID $($p.Id)"
