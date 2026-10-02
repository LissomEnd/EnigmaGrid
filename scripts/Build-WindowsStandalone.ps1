$ErrorActionPreference="Stop"
$root=Split-Path $PSScriptRoot -Parent
$py="$root\.venv-server\Scripts\python.exe"
$out="$root\dist\windows-candidate"
$work="$root\build\pyinstaller"
$spec="$root\build\spec"
Remove-Item $out,$work,$spec -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $out,$work,$spec | Out-Null

$tray=@("-m","PyInstaller","--noconfirm","--clean","--onefile","--windowed",
  "--name","EnigmaGrid","--distpath",$out,"--workpath","$work\tray","--specpath",$spec,
  "--hidden-import","pystray._win32","$root\worker\tray_app.py")
& $py @tray
if($LASTEXITCODE -ne 0){throw "Tray build failed"}
$worker=@("-m","PyInstaller","--noconfirm","--clean","--onefile","--noconsole",
  "--name","EnigmaGridWorker","--distpath",$out,"--workpath","$work\worker","--specpath",$spec,
  "--paths","$root\solver\runtime\src",
  "--add-data","$root\solver;solver",
  "--add-data","$root\worker\update_config.json;worker",
  "--add-data","$root\worker\update_public_key.json;worker",
  "--hidden-import","updater","$root\worker\worker.py")
& $py @worker
if($LASTEXITCODE -ne 0){throw "Worker build failed"}

$hashes=Get-ChildItem $out -File | Get-FileHash -Algorithm SHA256
$hashes | ForEach-Object {"$($_.Hash)  $([IO.Path]::GetFileName($_.Path))"} | Set-Content "$out\SHA256SUMS.txt" -Encoding ASCII
$zip="$root\dist\enigma-volunteer-windows-candidate.zip"
Remove-Item $zip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path "$out\*" -DestinationPath $zip -CompressionLevel Optimal
Write-Host "Built candidate:"
Get-ChildItem $out -File | Select-Object Name,Length | Format-Table -AutoSize
Get-FileHash $zip -Algorithm SHA256 | Format-List
