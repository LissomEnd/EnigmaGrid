param(
 [Parameter(Mandatory=$true)][string]$ServerUrl,
 [string]$RegistrationCode="",
 [Parameter(Mandatory=$true)][string]$ContributorName,
 [string]$ContributorKey="",
 [ValidateRange(0,100)][int]$CPUPercent=50,
 [ValidateRange(0,100)][int]$GPUPercent=0,
 [string]$InstallDir="$env:LOCALAPPDATA\EnigmaVolunteerGrid"
)
$ErrorActionPreference="Stop"
$root=Split-Path $PSScriptRoot -Parent
New-Item -ItemType Directory -Force "$InstallDir\worker" | Out-Null
Copy-Item "$root\worker\*.py" "$InstallDir\worker" -Force
Copy-Item "$root\worker\*.json" "$InstallDir\worker" -Force
Copy-Item "$root\solver" "$InstallDir\solver" -Recurse -Force
$py=(Get-Command py -ErrorAction Stop).Source
$pyw=(Get-Command pyw -ErrorAction Stop).Source
$state="$InstallDir\client.json"
$args=@("-3.13","$InstallDir\worker\worker.py","--server",$ServerUrl,"--registration-code",$RegistrationCode,"--name",$ContributorName,"--state",$state,"--register-only","--cpu-percent",$CPUPercent,"--gpu-percent",$GPUPercent)
if($ContributorKey){$args+=@("--contributor-key",$ContributorKey)}
& $py @args
if($LASTEXITCODE -ne 0){throw "Worker registration failed."}
$cmd = 'pyw -3.13 "{0}\worker\worker.py" --state "{0}\client.json" --server "{1}"' -f $InstallDir,$ServerUrl
$runKey="HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
New-Item -Path $runKey -Force | Out-Null
Set-ItemProperty -Path $runKey -Name "EnigmaVolunteerGrid" -Value $cmd
Start-Process -FilePath $pyw -ArgumentList @("-3.13","$InstallDir\worker\worker.py","--state",$state,"--server",$ServerUrl) -WindowStyle Hidden
Write-Host ("Installed and running. CPU="+$CPUPercent+"% GPU="+$GPUPercent+"%. No administrator privileges required.")
