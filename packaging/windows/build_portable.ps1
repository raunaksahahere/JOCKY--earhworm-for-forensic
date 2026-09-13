# Portable Windows release: the complete bundle as a single ZIP, no installer.
# Runs from any directory, including removable media, and writes its
# investigations to the workspace passed to launch_portable.ps1.
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$version = if ($env:JOCKY_VERSION) { $env:JOCKY_VERSION } else { '0.4.1' }
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "Invalid release version: $version" }

$bundle = Join-Path $root 'flutter_client\build\windows\x64\runner\Release'
if (-not (Test-Path "$bundle\backend\JOCKY-backend.exe")) {
  throw 'Build the complete Windows release bundle first: packaging\windows\build.ps1'
}

$out = Join-Path $root 'build\windows'
New-Item -ItemType Directory -Force $out | Out-Null
$archive = Join-Path $out "jocky-workstation-$version-windows-x64-portable.zip"
if (Test-Path $archive) { Remove-Item $archive }

# The launcher is included so the portable copy is usable without the repo.
Copy-Item (Join-Path $PSScriptRoot 'launch_portable.ps1') $bundle -Force
Compress-Archive -Path "$bundle\*" -DestinationPath $archive -CompressionLevel Optimal
Write-Host "Portable archive: $archive"
