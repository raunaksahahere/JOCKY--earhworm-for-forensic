$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Dashboard = Join-Path $Root "dashboard"
$DesktopApp = Join-Path $Root "desktop-app"
$BackendBuild = Join-Path $Root "desktop\backend-dist"
$BackendWork = Join-Path $Root "desktop\.pyinstaller"

Write-Host "=== JOCKY fully bundled Windows build ===" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python is required on the BUILD MACHINE only. The final target PC does not need Python."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node/npm is required on the BUILD MACHINE only. The final target PC does not need Node/npm."
}

Write-Host "[1/5] Installing Python build dependencies..." -ForegroundColor Yellow
python -m pip install -r (Join-Path $Root "requirements.txt")
python -m pip install pyinstaller==6.16.0

Write-Host "[2/5] Building production frontend..." -ForegroundColor Yellow
Push-Location $Dashboard
npm install
npm run build
Pop-Location

if (-not (Test-Path (Join-Path $Dashboard "dist\index.html"))) {
    throw "Frontend build did not produce dashboard/dist/index.html"
}

Write-Host "[3/5] Freezing Flask backend into a Windows executable..." -ForegroundColor Yellow
Remove-Item $BackendBuild -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $BackendWork -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $BackendBuild | Out-Null

Push-Location $Root
python -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --noconsole `
  --name JOCKY-backend `
  --distpath $BackendBuild `
  --workpath $BackendWork `
  --specpath $BackendWork `
  --paths $Root `
  --add-data "compiler\grammar.lark;compiler" `
  desktop\backend_entry.py
Pop-Location

if (-not (Test-Path (Join-Path $BackendBuild "JOCKY-backend\JOCKY-backend.exe"))) {
    throw "PyInstaller did not produce the backend executable."
}

Write-Host "[4/5] Installing Electron build dependencies..." -ForegroundColor Yellow
Push-Location $DesktopApp
npm install

Write-Host "[5/5] Packaging JOCKY installer + portable EXE..." -ForegroundColor Yellow
npm run dist
Pop-Location

Write-Host "" 
Write-Host "BUILD COMPLETE" -ForegroundColor Green
Write-Host "Installer and portable EXE are in:" -ForegroundColor Green
Write-Host (Join-Path $DesktopApp "release") -ForegroundColor White
Write-Host "The packaged application contains Chromium/Electron + the Python backend + the production frontend." -ForegroundColor Green
Write-Host "The TARGET Windows PC does NOT need Python, Node.js, npm, or a development server." -ForegroundColor Green
