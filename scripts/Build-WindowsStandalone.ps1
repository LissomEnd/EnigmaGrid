$ErrorActionPreference="Stop"
$root=Split-Path $PSScriptRoot -Parent
$py="$root\.venv-server\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) { $py=(Get-Command python -ErrorAction Stop).Source }
$out="$root\dist\windows-candidate"
$work="$root\build\pyinstaller"
$spec="$root\build\spec"
foreach ($buildTarget in @($out,$work,$spec)) {
  $resolvedTarget=[IO.Path]::GetFullPath($buildTarget)
  if (-not $resolvedTarget.StartsWith(([IO.Path]::GetFullPath($root)+'\'),[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Build cleanup path is outside repository'
  }
  Remove-Item -LiteralPath $resolvedTarget -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force $out,$work,$spec | Out-Null
$solverStage=Join-Path $work 'solver'
Get-ChildItem -LiteralPath "$root\solver" -Recurse -File | Where-Object {
  $_.Extension -in @('.py','.cl','.json','.txt') -and $_.FullName -notmatch '[\\/]__pycache__[\\/]'
} | ForEach-Object {
  $relative=$_.FullName.Substring((Join-Path $root 'solver').Length+1)
  $destination=Join-Path $solverStage $relative
  New-Item -ItemType Directory -Force (Split-Path $destination -Parent) | Out-Null
  Copy-Item -LiteralPath $_.FullName -Destination $destination
}

$commonMeta=@("--icon","$root\assets\enigma-grid.ico","--version-file","$root\assets\version_info.txt")
$tray=@("-m","PyInstaller","--noconfirm","--clean","--onefile","--windowed",
  "--name","EnigmaGrid","--distpath",$out,"--workpath","$work\tray","--specpath",$spec,
  "--hidden-import","pystray._win32") + $commonMeta + @("$root\worker\tray_app.py")
& $py @tray
if($LASTEXITCODE -ne 0){throw "Tray build failed"}
$worker=@("-m","PyInstaller","--noconfirm","--clean","--onefile","--console",
  "--name","EnigmaGridWorker","--distpath",$out,"--workpath","$work\worker","--specpath",$spec,
  "--paths","$root\solver\runtime\src",
  "--add-data","$solverStage;solver",
  "--add-data","$root\worker\update_config.json;worker",
  "--add-data","$root\worker\update_public_key.json;worker",
  "--hidden-import","updater","--collect-all","pyopencl",
  "--hidden-import","search.portable_search") + $commonMeta + @("$root\worker\worker.py")
& $py @worker
if($LASTEXITCODE -ne 0){throw "Worker build failed"}

$updater=@("-m","PyInstaller","--noconfirm","--clean","--onefile","--noconsole",
  "--name","EnigmaGridUpdater","--distpath",$out,"--workpath","$work\updater","--specpath",$spec,
  "--add-data","$root\worker\update_public_key.json;worker") + $commonMeta + @("$root\worker\updater_apply.py")
& $py @updater
if($LASTEXITCODE -ne 0){throw "Updater build failed"}
Copy-Item "$root\worker\release_config.json" "$out\release_config.json" -Force

$hashes=Get-ChildItem $out -File | Get-FileHash -Algorithm SHA256
$hashes | ForEach-Object {"$($_.Hash)  $([IO.Path]::GetFileName($_.Path))"} | Set-Content "$out\SHA256SUMS.txt" -Encoding ASCII
$zip="$root\dist\enigma-volunteer-windows-candidate.zip"
Remove-Item $zip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path "$out\*" -DestinationPath $zip -CompressionLevel Optimal

& $py "$root\scripts\create_installer_payload.py" $out "0.4.0"
if($LASTEXITCODE -ne 0){throw "Installer payload manifest failed"}
$setup=@("-m","PyInstaller","--noconfirm","--clean","--onefile","--windowed",
  "--name","EnigmaGridSetup","--distpath","$root\dist","--workpath","$work\setup","--specpath",$spec,
  "--add-data","$out\installer_payload.json;.",
  "--add-binary","$out\EnigmaGrid.exe;payload",
  "--add-binary","$out\EnigmaGridWorker.exe;payload",
  "--add-binary","$out\EnigmaGridUpdater.exe;payload",
  "--add-data","$out\release_config.json;payload") + $commonMeta + @("$root\worker\installer.py")
& $py @setup
if($LASTEXITCODE -ne 0){throw "Setup build failed"}
Remove-Item "$out\installer_payload.json" -Force

Write-Host "Built candidate:"
Get-ChildItem $out -File | Select-Object Name,Length | Format-Table -AutoSize
Get-FileHash $zip -Algorithm SHA256 | Format-List
Get-FileHash "$root\dist\EnigmaGridSetup.exe" -Algorithm SHA256 | Format-List
