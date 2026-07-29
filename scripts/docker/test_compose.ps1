param(
    [string]$ProjectRoot = "D:\stock_daily_app",
    [string]$OutputRoot = "D:\google\test_results",
    [switch]$Headed
)

$script = Join-Path $PSScriptRoot "test_stage6_5.ps1"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script `
    -ProjectRoot $ProjectRoot `
    -OutputRoot $OutputRoot `
    -Headed:$Headed
exit $LASTEXITCODE
