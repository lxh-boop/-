param(
    [switch]$NoBuild,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$startScript = Join-Path $projectRoot "scripts\docker\start_compose.ps1"
if (-not (Test-Path -LiteralPath $startScript)) {
    throw "Missing production Compose launcher: $startScript"
}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript `
    -ProjectRoot $projectRoot `
    -NoBuild:$NoBuild `
    -NoBrowser:$NoBrowser
exit $LASTEXITCODE
