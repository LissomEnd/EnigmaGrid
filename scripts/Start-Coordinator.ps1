$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$py="$root\.venv-server\Scripts\python.exe"
$pidFile="$root\state\coordinator_process.json"
if(Test-Path $pidFile){
  try{$old=Get-Content $pidFile -Raw|ConvertFrom-Json;$proc=Get-Process -Id ([int]$old.pid) -ErrorAction SilentlyContinue}catch{$proc=$null}
  if($proc){Write-Host "Coordinator already running PID $($proc.Id)";exit 0}
}
$out="$root\state\coordinator.stdout.log";$err="$root\state\coordinator.stderr.log"
$p=Start-Process -FilePath $py -ArgumentList @("$root\server\coordinator.py") -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
@{pid=$p.Id;started=(Get-Date).ToString('o');stdout=$out;stderr=$err}|ConvertTo-Json|Set-Content $pidFile
Write-Host "Coordinator started PID $($p.Id)"
