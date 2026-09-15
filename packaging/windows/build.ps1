# Complete Windows release bundle: Flutter client plus the frozen engine.
# Must run on Windows: PyInstaller and Flutter both produce native output only.
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$backend = if ($env:JOCKY_BACKEND_DIST) { $env:JOCKY_BACKEND_DIST }
           else { Join-Path $root 'backend-dist\JOCKY-backend' }

if (-not (Test-Path "$backend\JOCKY-backend.exe")) {
  throw "No engine at $backend. Build it first: .venv\Scripts\python.exe scripts\build_backend.py"
}

Push-Location (Join-Path $root 'flutter_client')
try {
  $env:JOCKY_BACKEND_DIST = $backend
  flutter pub get;   if ($LASTEXITCODE -ne 0) { throw 'Flutter dependencies failed' }
  flutter analyze;   if ($LASTEXITCODE -ne 0) { throw 'Flutter analysis failed' }
  flutter test;      if ($LASTEXITCODE -ne 0) { throw 'Flutter tests failed' }
  flutter build windows --release
  if ($LASTEXITCODE -ne 0) {
    # MSBuild reports a failing install step as the batch wrapper it ran and
    # nothing else -- twelve lines of ":cmEnd / exit /b %1" and no cause. The
    # verbose build carries CMake's own message, which is the one that says
    # what could not be copied and from where.
    Write-Host ''
    Write-Host '--- the build failed; repeating it verbosely for the real error ---'
    flutter build windows --release --verbose 2>&1 |
      Select-String -Pattern 'CMake Error', 'CMake Warning', 'file INSTALL',
                             'JOCKY:', 'cannot|does not exist|Permission|denied',
                             'error [A-Z]+[0-9]+' |
      Select-Object -First 40 | ForEach-Object { Write-Host "  $_" }
    throw 'Flutter build failed'
  }

  $bundle = Join-Path $root 'flutter_client\build\windows\x64\runner\Release'

  # windows/CMakeLists.txt installs the engine into the bundle. Copy here only
  # if that rule did not fire, so a stale CMake cache cannot ship a client with
  # no engine.
  if (-not (Test-Path "$bundle\backend\JOCKY-backend.exe")) {
    Write-Warning 'CMake did not install the engine; copying it directly.'
    New-Item -ItemType Directory -Force "$bundle\backend" | Out-Null
    Copy-Item "$backend\*" "$bundle\backend" -Recurse -Force
  }

  # Refuse to call an unrunnable bundle a release.
  foreach ($required in @("$bundle\jocky_client.exe",
                          "$bundle\backend\JOCKY-backend.exe",
                          "$bundle\backend\_internal")) {
    if (-not (Test-Path $required)) { throw "Release bundle is incomplete: $required is missing" }
  }
  Write-Host "Complete release bundle: $bundle"
} finally { Pop-Location }
