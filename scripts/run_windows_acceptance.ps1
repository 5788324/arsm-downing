param(
    [Parameter(Mandatory=$true)][string]$EvidenceDir,
    [string]$ActiveDb = "",
    [string]$Rj = "RJ01575399",
    [string]$Mirror = "https://api.asmr-200.com",
    [string]$Proxy = "",
    [int64]$MaxBytes = 67108864,
    [switch]$SkipLive,
    [switch]$LaunchUi
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EvidenceFull = [System.IO.Path]::GetFullPath($EvidenceDir)
$RepoFull = [System.IO.Path]::GetFullPath($RepoRoot)
if ($EvidenceFull.StartsWith($RepoFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "EvidenceDir 必须位于仓库之外: $EvidenceFull"
}
if (Test-Path $EvidenceFull) {
    $existing = Get-ChildItem -Force $EvidenceFull
    if ($existing.Count -gt 0) { throw "EvidenceDir 必须为空: $EvidenceFull" }
} else {
    New-Item -ItemType Directory -Path $EvidenceFull | Out-Null
}

$Venv = Join-Path $EvidenceFull ".venv"
$PythonSelector = @("-3.12")
py -3.12 --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    $PythonSelector = @("-3.10")
    py -3.10 --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "未找到 Python 3.12 或 3.10"
    }
}
py @PythonSelector -m venv $Venv
$Python = Join-Path $Venv "Scripts\python.exe"
& $Python -m pip install --disable-pip-version-check -r (Join-Path $RepoRoot "requirements-dev.txt")

$RunnerArgs = @(
    (Join-Path $RepoRoot "scripts\windows_acceptance.py"),
    "--evidence-dir", (Join-Path $EvidenceFull "evidence"),
    "--rj", $Rj,
    "--mirror", $Mirror,
    "--max-bytes", $MaxBytes
)
if ($ActiveDb) { $RunnerArgs += @("--active-db", $ActiveDb) }
if ($Proxy) { $RunnerArgs += @("--proxy", $Proxy) }
if ($SkipLive) { $RunnerArgs += "--skip-live" }
if ($LaunchUi) { $RunnerArgs += "--launch-ui" }

& $Python @RunnerArgs
exit $LASTEXITCODE
