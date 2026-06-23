# Windows PowerShell syntax check
# Usage: .\scripts\check_syntax.ps1

Write-Host "=== EchoVault Syntax Check ===" -ForegroundColor Cyan
Write-Host ""

$failed = $false

$files = @(
    "main.py"
) + (Get-ChildItem core -Filter *.py).FullName +
    (Get-ChildItem ui -Filter *.py).FullName +
    (Get-ChildItem ui/views -Filter *.py).FullName +
    (Get-ChildItem scripts -Filter *.py).FullName

foreach ($f in $files) {
    python -m py_compile $f 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FAIL: $f" -ForegroundColor Red
        $failed = $true
    }
}

Write-Host ""
if (-not $failed) {
    Write-Host "ALL FILES PASSED" -ForegroundColor Green
} else {
    Write-Host "SOME FILES FAILED" -ForegroundColor Red
}
