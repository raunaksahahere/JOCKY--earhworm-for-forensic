$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$backend = Join-Path $root 'backend-dist\JOCKY-backend'
if (-not (Test-Path "$backend\JOCKY-backend.exe")) { throw 'Run .venv\Scripts\python.exe scripts\build_backend.py first' }
Push-Location (Join-Path $root 'flutter_client')
try {
  flutter pub get
  if ($LASTEXITCODE -ne 0) { throw 'Flutter dependencies failed' }
  flutter analyze
  if ($LASTEXITCODE -ne 0) { throw 'Flutter analysis failed' }
  flutter test
  if ($LASTEXITCODE -ne 0) { throw 'Flutter tests failed' }
  flutter build windows --release
  if ($LASTEXITCODE -ne 0) { throw 'Flutter build failed' }
  $bundle = Join-Path $root 'flutter_client\build\windows\x64\runner\Release'
  New-Item -ItemType Directory -Force "$bundle\backend" | Out-Null
  Copy-Item "$backend\*" "$bundle\backend" -Recurse -Force
} finally { Pop-Location }
