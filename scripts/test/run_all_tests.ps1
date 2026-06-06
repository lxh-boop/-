$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ReportDir = Join-Path $Root "outputs\test_reports"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

Push-Location $Root

py -m pytest tests/unit -v *> (Join-Path $ReportDir "pytest_unit_report.txt")
$UnitExit = $LASTEXITCODE

py -m pytest tests/integration -v *> (Join-Path $ReportDir "pytest_integration_report.txt")
$IntegrationExit = $LASTEXITCODE

py -m pytest tests/e2e -v *> (Join-Path $ReportDir "pytest_e2e_report.txt")
$E2EExit = $LASTEXITCODE

Pop-Location

Write-Host "unit exit code: $UnitExit"
Write-Host "integration exit code: $IntegrationExit"
Write-Host "e2e exit code: $E2EExit"

if ($UnitExit -ne 0 -or $IntegrationExit -ne 0) {
    exit 1
}

exit 0
