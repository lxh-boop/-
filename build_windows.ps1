Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

function Assert-InProjectRoot {
    param([string]$PathToCheck)
    $root = (Resolve-Path -LiteralPath $ProjectRoot).Path.TrimEnd('\')
    $full = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $PathToCheck)).TrimEnd('\')
    if (-not ($full.Equals($root, [System.StringComparison]::OrdinalIgnoreCase) -or $full.StartsWith($root + "\", [System.StringComparison]::OrdinalIgnoreCase))) {
        throw "Refusing to operate outside project root: $full"
    }
    return $full
}

function Remove-ProjectDirectoryIfExists {
    param([string]$RelativePath)
    $target = Assert-InProjectRoot $RelativePath
    if (Test-Path -LiteralPath $target) {
        Write-Host "[Clean] Removing $target"
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

if (-not (Test-Path -LiteralPath ".\app.py") -or -not (Test-Path -LiteralPath ".\desktop_launcher.py")) {
    throw "Please run this script from the stock_daily_app project root."
}

$PythonCommand = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }

Write-Host "[Project] $ProjectRoot"
Write-Host "[Python] $PythonCommand"
& $PythonCommand --version

$Version = & $PythonCommand -c "from app_version import APP_VERSION; print(APP_VERSION)"
Write-Host "[Version] $Version"

Write-Host "[Check] Build dependencies"
& $PythonCommand -c "import streamlit, PyInstaller, webview; print('streamlit/PyInstaller/pywebview OK')"

Write-Host "[Prepare] Distribution assets"
& $PythonCommand .\scripts\prepare_distribution_assets.py

Remove-ProjectDirectoryIfExists "build"
Remove-ProjectDirectoryIfExists "dist"

Write-Host "[Build] PyInstaller onedir"
& $PythonCommand -m PyInstaller --noconfirm --clean .\stock_daily_app.spec

$ExePath = Join-Path $ProjectRoot "dist\StockDailyApp\StockDailyApp.exe"
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "PyInstaller finished but executable was not found: $ExePath"
}
Write-Host "[OK] EXE: $ExePath"

$IsccCandidates = @(
    @(
        "ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Get-Command $_ -ErrorAction SilentlyContinue -CommandType Application) }
)

if ($IsccCandidates.Count -gt 0) {
    $Iscc = $IsccCandidates[0].Source
    Write-Host "[Installer] Inno Setup found: $Iscc"
    & $Iscc "/DMyAppVersion=$Version" ".\installer\StockDailyApp.iss"
    $SetupPath = Join-Path $ProjectRoot "installer_output\StockDailyApp_Setup_$Version.exe"
    if (-not (Test-Path -LiteralPath $SetupPath)) {
        throw "Inno Setup finished but installer was not found: $SetupPath"
    }
    Write-Host "[OK] Installer: $SetupPath"
} else {
    Write-Host "[Installer] Inno Setup ISCC.exe not found. Install Inno Setup 6 to generate the installer."
    Write-Host "[Installer] PyInstaller build succeeded; installer generation was skipped."
}

Write-Host "[Verify] Distribution"
& $PythonCommand .\scripts\verify_distribution.py
