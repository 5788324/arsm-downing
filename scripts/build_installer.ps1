param(
    [string]$Python = "py -3.12",
    [string]$OutputDir = "release",
    [switch]$SkipPortableBuild
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not $SkipPortableBuild) {
    & (Join-Path $PSScriptRoot "build_windows.ps1") -Python $Python -OutputDir $OutputDir
}

$VenvPython = Join-Path $RepoRoot ".venv-build\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    # CI already provides the locked Python through actions/setup-python.
    $VenvPython = (Get-Command $Python.Split(" ")[0] -ErrorAction Stop).Source
}

$SourceDir = Join-Path $RepoRoot "dist\ARSM-Suite"
if (-not (Test-Path -LiteralPath (Join-Path $SourceDir "ARSM-Suite.exe"))) {
    throw "Portable folder is missing: $SourceDir"
}

$Iscc = (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue).Source
if (-not $Iscc) {
    $Candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    $Iscc = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $Iscc) {
    throw "Inno Setup 6 was not found. Install JRSoftware.InnoSetup, then retry."
}

$ReleaseRoot = Join-Path $RepoRoot $OutputDir
New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
$Version = & $VenvPython -c "from core.version import APP_VERSION; print(APP_VERSION)"
$Script = Join-Path $RepoRoot "packaging\ARSM-Suite.iss"
& $Iscc "/DAppVersion=$Version" "/DSourceDir=$SourceDir" "/DOutputDir=$ReleaseRoot" $Script
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE" }

$Installer = Join-Path $ReleaseRoot "ARSM-Suite-$Version-setup.exe"
if (-not (Test-Path -LiteralPath $Installer)) { throw "Installer was not produced: $Installer" }
$Hash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
"$Hash  $(Split-Path $Installer -Leaf)" | Set-Content -LiteralPath "$Installer.sha256" -Encoding ascii
Write-Host "Installer complete: $Installer"
Write-Host "SHA-256: $Hash"
