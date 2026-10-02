$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$zip="$root\dist\enigma-volunteer-dev.zip"
$stage=Join-Path $env:TEMP 'enigma-volunteer-bundle-stage'
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$stage\worker","$stage\solver" | Out-Null
Copy-Item "$root\worker\*.py","$root\worker\*.json","$root\worker\*.ps1" "$stage\worker" -Force
& robocopy "$root\solver" "$stage\solver" /E /XD __pycache__ /XF *.pyc *.pyo *.nbc *.nbi | Out-Null
if($LASTEXITCODE -gt 7){throw "robocopy failed with exit code $LASTEXITCODE"}
if(Test-Path $zip){Remove-Item $zip -Force}
Compress-Archive -Path "$stage\worker","$stage\solver" -DestinationPath $zip -CompressionLevel Optimal
Remove-Item $stage -Recurse -Force
$h=Get-FileHash $zip -Algorithm SHA256
Write-Host "$($h.Hash)  $zip"
