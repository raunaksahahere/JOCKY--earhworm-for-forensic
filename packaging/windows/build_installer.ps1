$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
if (-not (Test-Path "$root\flutter_client\build\windows\x64\runner\Release\backend\JOCKY-backend.exe")) { throw 'Build complete Windows release first' }
iscc "$root\flutter_client\packaging\windows\jocky-workstation.iss"
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
