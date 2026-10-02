$ErrorActionPreference="Stop"
$root=Split-Path $PSScriptRoot -Parent
$py="$root\.venv-server\Scripts\python.exe"
$out="$root\dist\windows-candidate"
$work="$root\build\pyinstaller"
$spec="$root\build\spec"
Remove-Item $out,$work,$spec -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $out,$work,$spec | Out-Null

$commonMeta=@("--icon","$root\assets\enigma-grid.ico","--version-file","$root\assets\version_info.txt")
$tray=@("-m","PyInstaller","--noconfirm","--clean","--onefile","--windowed",
  "--name","EnigmaGrid","--distpath",$out,"--workpath","$work\tray","--specpath",$spec,
  "--hidden-import","pystray._win32") + $commonMeta + @("$root\worker\tray_app.py")
& $py @tray
if($LASTEXITCODE -ne 0){throw "Tray build failed"}
$worker=@("-m","PyInstaller","--noconfirm","--clean","--onefile","--noconsole",
  "--name","EnigmaGridWorker","--distpath",$out,"--workpath","$work\worker","--specpath",$spec,
  "--paths","$root\solver\runtime\src",
  "--add-data","$root\solver;solver",
  "--add-data","$root\worker\update_config.json;worker",
  "--add-data","$root\worker\update_public_key.json;worker",
  "--hidden-import","updater") + $commonMeta + @("$root\worker\worker.py")
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

& $py "$root\scripts\create_installer_payload.py" $out "0.3.0"
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
