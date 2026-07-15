# Builds the Seshat desktop app into a Windows installer.
# Run from the repo root in a Python environment that has the app installed:
#     python -m pip install -e ".[desktop]" pyinstaller
#     powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Needs Node.js on PATH: the React cockpit is built first and bundled into the
# exe, so the frozen FastAPI server has a UI to serve.
#
# Produces:
#   dist\Seshat\Seshat.exe   (the onedir app)
#   dist\SeshatSetup.exe      (the installer, if Inno Setup is installed)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

Write-Host "== Cleaning previous build ==" -ForegroundColor Cyan
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

Write-Host "== Frontend (npm) ==" -ForegroundColor Cyan
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm not found. Install Node.js (https://nodejs.org) and re-run."
}
Push-Location frontend
try {
    # npm ci installs the lockfile exactly, so the bundled UI is reproducible.
    & npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
} finally {
    Pop-Location
}
$static = "seshat\api\static\index.html"
if (-not (Test-Path $static)) { throw "The frontend build did not produce $static" }
Write-Host "Built the React cockpit into seshat\api\static" -ForegroundColor Green

Write-Host "== PyInstaller ==" -ForegroundColor Cyan
python -m PyInstaller --noconfirm packaging\seshat.spec
if (-not (Test-Path "dist\Seshat\Seshat.exe")) {
    throw "PyInstaller did not produce dist\Seshat\Seshat.exe"
}
Write-Host "Built dist\Seshat\Seshat.exe" -ForegroundColor Green

# Compile the installer if Inno Setup's ISCC is available.
$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    $guess = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (Test-Path $guess) { $iscc = $guess }
}
if ($iscc) {
    Write-Host "== Inno Setup ==" -ForegroundColor Cyan
    & $iscc packaging\seshat.iss
    Write-Host "Built dist\SeshatSetup.exe" -ForegroundColor Green
} else {
    Write-Host "Inno Setup (ISCC.exe) not found; skipping installer." -ForegroundColor Yellow
    Write-Host "Install it from https://jrsoftware.org/isinfo.php and re-run." -ForegroundColor Yellow
}
