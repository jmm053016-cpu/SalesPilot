[CmdletBinding()]
param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment Python not found: $python"
}

Write-Host "[1/3] Running Python compilation check"
& $python -m compileall -q agent analytics charts data_sources models reports storage ui workflow tests app.py
if ($LASTEXITCODE -ne 0) {
    throw "Python compilation check failed with exit code $LASTEXITCODE"
}

if (-not $SkipTests) {
    Write-Host "[2/3] Running deterministic test suite"
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "Test suite failed with exit code $LASTEXITCODE"
    }
} else {
    Write-Host "[2/3] Skipping deterministic test suite"
}

Write-Host "[3/3] Checking for executable code in the new sales-agent surface"
$forbidden = rg -n --glob '*.py' '(^|[^A-Za-z])(exec|eval)\s*\(' agent analytics charts data_sources models reports storage ui workflow
if ($LASTEXITCODE -eq 0) {
    $forbidden | Write-Error
    throw "Forbidden exec/eval usage found in the sales-agent surface"
}
if ($LASTEXITCODE -gt 1) {
    throw "Static security check failed with exit code $LASTEXITCODE"
}

Write-Host "Release checks passed."
