param([Parameter(Mandatory=$true)][string]$Domain)
$ErrorActionPreference='Stop'
$here=Split-Path $MyInvocation.MyCommand.Path -Parent
$example=Join-Path $here 'server.production.example.json'
$target=Join-Path $here 'server.production.json'
$envFile=Join-Path $here '.env'
if(Test-Path $target){throw 'server.production.json already exists; refusing to overwrite'}
if(Test-Path $envFile){throw '.env already exists; refusing to overwrite secrets'}
Copy-Item $example $target
$code=([guid]::NewGuid().ToString('N')+[guid]::NewGuid().ToString('N'))
@("GRID_DOMAIN=$Domain","GRID_REGISTRATION_CODE=$code") | Set-Content $envFile -Encoding ASCII
Write-Host 'Deployment files prepared. Keep server.production.json and .env private.'
Write-Host ('Registration code: '+$code)
