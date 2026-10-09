$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$python=Join-Path $root '.venv-server\Scripts\python.exe'
$script=Join-Path $PSScriptRoot 'c4_autoarm.py'
if(-not (Test-Path $python) -or -not (Test-Path $script)){throw 'Missing C4 autoarm prerequisites'}
& $python $script --arm-if-ready
exit $LASTEXITCODE
