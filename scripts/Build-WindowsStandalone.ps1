param([string]$NativeSolverDirectory)
$ErrorActionPreference="Stop"
$root=Split-Path $PSScriptRoot -Parent
if (-not $NativeSolverDirectory) { $NativeSolverDirectory=Join-Path $root 'worker\native\build\install' }
$nativeLibrary=Join-Path $NativeSolverDirectory 'enigmagrid_solver.dll'
$nativeShader=Join-Path $NativeSolverDirectory 'bounded_solver.spv'
foreach ($nativeAsset in @($nativeLibrary,$nativeShader)) {
  if (-not (Test-Path -LiteralPath $nativeAsset -PathType Leaf)) {
    throw "Missing bounded Vulkan asset: $nativeAsset. Build/install worker/native first or specify -NativeSolverDirectory."
  }
}
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
$solverRoot=[IO.Path]::GetFullPath((Join-Path $root 'solver'))+'\'
$sourceProvenance=@()
Get-Content -LiteralPath "$root\scripts\solver-runtime-files.txt" | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith('#') } | ForEach-Object {
  $relative=$_.Trim()
  if([IO.Path]::IsPathRooted($relative) -or ($relative -split '[/\\]') -contains '..'){throw 'Unsafe solver manifest path'}
  $source=[IO.Path]::GetFullPath((Join-Path $solverRoot $relative))
  if(-not $source.StartsWith($solverRoot,[StringComparison]::OrdinalIgnoreCase)){throw 'Solver input outside source root'}
  if(-not (Test-Path -LiteralPath $source -PathType Leaf)){throw "Missing reviewed solver input: $relative"}
  if((Get-Item -LiteralPath $source).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Solver input cannot be a reparse point'}
  $destination=Join-Path $solverStage $relative
  New-Item -ItemType Directory -Force (Split-Path $destination -Parent) | Out-Null
  Copy-Item -LiteralPath $source -Destination $destination
  $sourceProvenance+=@{path=('solver/'+$relative.Replace('\','/'));sha256=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()}
}
$sourceProvenance | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath "$root\dist\solver-source-provenance.json" -Encoding UTF8

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
  "--add-binary","$nativeLibrary;worker/native",
  "--add-data","$nativeShader;worker/native",
  "--hidden-import","bounded_gpu_qualification",
  "--hidden-import","gpu_lane_qualification",
  "--hidden-import","portable_batch_qualification",
  "--hidden-import","search.vulkan_bounded",
  "--hidden-import","updater","--collect-all","pyopencl",
  "--hidden-import","search.portable_search","--hidden-import","search.process_map","--hidden-import","search.windows_spawn",
  "--hidden-import","search.bounded_crib") + $commonMeta + @("$root\worker\worker.py")
& $py @worker
if($LASTEXITCODE -ne 0){throw "Worker build failed"}

$updater=@("-m","PyInstaller","--noconfirm","--clean","--onefile","--noconsole",
  "--name","EnigmaGridUpdater","--distpath",$out,"--workpath","$work\updater","--specpath",$spec,
  "--add-data","$root\worker\update_public_key.json;worker") + $commonMeta + @("$root\worker\updater_apply.py")
& $py @updater
if($LASTEXITCODE -ne 0){throw "Updater build failed"}
Copy-Item "$root\worker\release_config.json" "$out\release_config.json" -Force

& $py "$root\scripts\collect_licenses.py" "$out\LICENSES.txt"
if($LASTEXITCODE -ne 0){throw "License collection failed"}

$hashes=Get-ChildItem $out -File | Get-FileHash -Algorithm SHA256
$hashes | ForEach-Object {"$($_.Hash)  $([IO.Path]::GetFileName($_.Path))"} | Set-Content "$out\SHA256SUMS.txt" -Encoding ASCII
$zip="$root\dist\enigma-volunteer-windows-candidate.zip"
Remove-Item $zip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path "$out\*" -DestinationPath $zip -CompressionLevel Optimal

& $py "$root\scripts\create_installer_payload.py" $out "0.5.1"
if($LASTEXITCODE -ne 0){throw "Installer payload manifest failed"}
$setup=@("-m","PyInstaller","--noconfirm","--clean","--onefile","--windowed",
  "--name","EnigmaGridSetup","--distpath","$root\dist","--workpath","$work\setup","--specpath",$spec,
  "--add-data","$out\installer_payload.json;.",
  "--add-binary","$out\EnigmaGrid.exe;payload",
  "--add-binary","$out\EnigmaGridWorker.exe;payload",
  "--add-binary","$out\EnigmaGridUpdater.exe;payload",
  "--add-data","$out\release_config.json;payload",
  "--add-data","$out\LICENSES.txt;payload") + $commonMeta + @("$root\worker\installer.py")
& $py @setup
if($LASTEXITCODE -ne 0){throw "Setup build failed"}
Remove-Item "$out\installer_payload.json" -Force

Write-Host "Built candidate:"
Get-ChildItem $out -File | Select-Object Name,Length | Format-Table -AutoSize
Get-FileHash $zip -Algorithm SHA256 | Format-List
Get-FileHash "$root\dist\EnigmaGridSetup.exe" -Algorithm SHA256 | Format-List
