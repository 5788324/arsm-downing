param(
    [string]$Python = "py -3.12",
    [string]$OutputDir = "release"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Venv = Join-Path $RepoRoot ".venv-build"
if (-not (Test-Path $Venv)) {
    Invoke-Expression "$Python -m venv `"$Venv`""
}

$Py = Join-Path $Venv "Scripts\python.exe"
& $Py -m pip install --disable-pip-version-check -r requirements-build.txt
& $Py -m pytest
& $Py -m PyInstaller --clean --noconfirm ARSMSuite.spec

$ReleaseRoot = Join-Path $RepoRoot $OutputDir
New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
$Version = & $Py -c "from core.version import APP_VERSION; print(APP_VERSION)"
$ZipPath = Join-Path $ReleaseRoot "ARSM-Suite-$Version-windows-x64.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path (Join-Path $RepoRoot "dist\ARSM-Suite\*") -DestinationPath $ZipPath

$Hash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$HashFile = "$ZipPath.sha256"
"$Hash  $(Split-Path $ZipPath -Leaf)" | Set-Content -Encoding ascii $HashFile

Write-Host "Build complete: $ZipPath"
Write-Host "SHA-256: $Hash"
